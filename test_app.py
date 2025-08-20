#!/usr/bin/env python3
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    return "<h1>Test Flask App Working!</h1><p>If you see this, Flask is running correctly.</p>"

@app.route('/template_test')
def template_test():
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Template error: {e}"

if __name__ == '__main__':
    print("Starting test Flask app...")
    print("Go to: http://127.0.0.1:5000")
    print("Template test: http://127.0.0.1:5000/template_test")
    app.run(debug=True, host='127.0.0.1', port=5000)