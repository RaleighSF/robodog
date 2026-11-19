#!/usr/bin/env bash
# Build and deploy the re:Invent (AWS) stack, then publish the AWS-themed booth
# dashboard to Amplify. Idempotent; secrets stay in deploy/aws/secrets (gitignored).
#   AWS_PROFILE=dev deploy/aws/deploy.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# One region for every call and for the Thor's edge config (the profile's own
# region could differ): resolve it once and export it to the CLI.
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
STACK="${STACK:-watchdog-reinvent}"
SECRETS="$REPO/deploy/aws/secrets"; mkdir -p "$SECRETS"; chmod 700 "$SECRETS"
BUILD="$REPO/build/aws-lambda"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ARTIFACTS="watchdog-cfn-artifacts-$ACCOUNT-$REGION"

echo "== build Lambda package (python3.12, arm64)"
rm -rf "$BUILD"; mkdir -p "$BUILD/agent_assets/knowledge"
cp "$REPO"/cloud/query_api/{aws_handler.py,aws_ingest.py,api_core.py,realtime.py} "$BUILD/"
cp -R "$REPO/cloud/query_api/backends" "$REPO/cloud/query_api/agents" "$BUILD/"
cp "$REPO/cloud/agent/instructions.md" "$BUILD/agent_assets/"
cp "$REPO/cloud/agent/knowledge/go2_health.md" "$BUILD/agent_assets/knowledge/"
python3 -m pip install -q --target "$BUILD" --platform manylinux2014_aarch64 --implementation cp \
  --python-version 3.12 --only-binary=:all: "anthropic[bedrock]==2.3.0"
find "$BUILD" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "== staff passcode"
[ -s "$SECRETS/staff.key" ] || { python3 -c "import secrets; print(secrets.token_urlsafe(24))" > "$SECRETS/staff.key"; chmod 600 "$SECRETS/staff.key"; }

echo "== package + deploy CloudFormation ($STACK)"
aws s3api head-bucket --bucket "$ARTIFACTS" 2>/dev/null || {
  if [ "$REGION" = us-east-1 ]; then aws s3api create-bucket --bucket "$ARTIFACTS" >/dev/null
  else aws s3api create-bucket --bucket "$ARTIFACTS" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null; fi
  aws s3api put-public-access-block --bucket "$ARTIFACTS" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true; }
aws cloudformation package --template-file "$REPO/deploy/aws/template.yaml" --s3-bucket "$ARTIFACTS" \
  --output-template-file "$REPO/build/aws-packaged.yaml" >/dev/null
EXPIRES=$(( $(date +%s) + 180 * 86400 ))
aws cloudformation deploy --stack-name "$STACK" --template-file "$REPO/build/aws-packaged.yaml" \
  --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "StaffKey=$(cat "$SECRETS/staff.key")" "ApiKeyExpires=$EXPIRES"
out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
API_URL="$(out ApiUrl)"; APP_ID="$(out DashboardAppId)"; DASH="$(out DashboardUrl)"

echo "== Thor edge credentials (send-only IAM user)"
if [ ! -s "$SECRETS/aws-edge.json" ]; then
  aws iam create-access-key --user-name "$(out EdgeUserName)" --query AccessKey --output json | python3 -c "
import json,sys; k=json.load(sys.stdin)
print(json.dumps({'access_key_id': k['AccessKeyId'], 'secret_access_key': k['SecretAccessKey'], 'region': '$REGION',
                  'stream': '$(out StreamName)', 'appsync_http': '$(out EventApiHttp)', 'channel': '/motion/booth'}, indent=2))" > "$SECRETS/aws-edge.json"
  chmod 600 "$SECRETS/aws-edge.json"
fi

echo "== dashboard (THEME=aws) -> Amplify"
( cd "$REPO/cloud/booth-dashboard" && THEME=aws QUERY_API_URL="${API_URL%/}/api" npm run build >/dev/null )
rm -f "$REPO/build/dashboard.zip"; ( cd "$REPO/cloud/booth-dashboard/out" && zip -qr "$REPO/build/dashboard.zip" . )
JOB=$(aws amplify create-deployment --app-id "$APP_ID" --branch-name main --output json)
curl -sf -X PUT -H "Content-Type: application/zip" --upload-file "$REPO/build/dashboard.zip" \
  "$(echo "$JOB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["zipUploadUrl"])')"
aws amplify start-deployment --app-id "$APP_ID" --branch-name main \
  --job-id "$(echo "$JOB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["jobId"])')" >/dev/null

echo "API:       $API_URL"
echo "Dashboard: $DASH"
