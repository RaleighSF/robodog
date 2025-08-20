#!/usr/bin/env python3
from flask import Flask, render_template
import os
import traceback

app = Flask(__name__)

@app.route('/')
def index():
    try:
        print("Attempting to render template...")
        print("Template folder:", app.template_folder)
        print("Templates exist:", os.path.exists('templates/index.html'))
        return render_template('index.html')
    except Exception as e:
        print("Error in template rendering:")
        traceback.print_exc()
        return f"Template Error: {str(e)}"

@app.route('/simple')
def simple():
    return "<h1>Simple route works!</h1>"

if __name__ == '__main__':
    print("Template folder path:", os.path.abspath('templates'))
    print("Index.html exists:", os.path.exists('templates/index.html'))
    app.run(debug=True, host='127.0.0.1', port=5000)