#!/usr/bin/env python3
import os
import json
import logging
import uuid
import queue
import threading
import tempfile
import shutil
import datetime
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai
from pool_manager import MultiProviderManager

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- Global State & Pool Management ---
pool_manager = MultiProviderManager()

# Use the keys that specifically listed models successfully
VALID_GEMINI_KEYS = [
    'AIzaSyBFa6ZZ7-xpgtnnJPSRhfQ1eaziZipLYbo', 
    'AIzaSyBS8VX3BDSyhmlRNfsNtj4bJoSncAQrx1k', 
    'AIzaSyBh6-uxvCwewkquh55q7K36_EtBh_cD4cg', 
    'AIzaSyBjdA_uD4lOzeIIA3zz5ES8061KTjqzK18', 
    'AIzaSyC82f9oN0sa29A1i3FSKVzWrC9jidP1knc', 
    'AIzaSyCIpsI4BZy9qL2vs7IfrJpYgAtfWz7CgAA', 
    'AIzaSyCTynAE1JLInzifyZVv69YsDZEK6g2mRSY', 
    'AIzaSyCeO5e0hZHKUahlPF64A1TQJl8H8bqPhjg', 
    'AIzaSyDp2ZeOgLZ19_LEEkzEQzb_yDsOnfip0y8'
]
pool_manager.setup_pool('gemini', VALID_GEMINI_KEYS)

tasks = {}
task_queue = queue.Queue()

# --- Translation Logic ---
def translate_content(content, source_lang="Chinese", target_lang="English"):
    provider = os.getenv('TRANSLATION_PROVIDER', 'gemini').lower()
    # SWITCHED TO GEMINI 2.5 FLASH as requested
    model_name = 'gemini-2.5-flash'
    
    prompt = f"""You are a professional translator specializing in software documentation.
Translate the following {source_lang} markdown content to {target_lang}.
Preserve all markdown formatting, code blocks, and technical terms.
Ensure the tone is professional and technical.

Content:
{content}"""

    max_retries = 3
    for attempt in range(max_retries):
        key = pool_manager.get_key(provider)
        if not key:
            raise Exception(f"No valid keys available for provider: {provider}")
        
        try:
            if provider == 'gemini':
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text
            else:
                raise Exception(f"Unsupported provider: {provider}")
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed with key [...{key[-4:]}]: {e}")
            pool_manager.report_failure(provider, key, e)
            # Add backoff for rate limits
            if "429" in str(e):
                time.sleep(10)
            if attempt == max_retries - 1:
                raise e

# --- Batch Processing Worker ---
def worker():
    while True:
        task_id = task_queue.get()
        if task_id is None: break
        
        task = tasks[task_id]
        task['status'] = 'cloning'
        
        temp_dir = tempfile.mkdtemp()
        try:
            repo_url = f"https://github.com/{task['owner']}/{task['repo']}.git"
            subprocess.run(["git", "clone", "-b", task['branch'], repo_url, temp_dir], check=True)
            
            md_files = []
            for root, _, files in os.walk(temp_dir):
                if '.git' in root: continue
                for f in files:
                    if f.endswith('.md'):
                        md_files.append(os.path.relpath(os.path.join(root, f), temp_dir))
            
            task['progress']['total'] = len(md_files)
            task['status'] = 'translating'
            
            storage_path = os.getenv('LOCAL_STORAGE_PATH', './translations')
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = os.path.join(storage_path, task['owner'], task['repo'], timestamp)
            os.makedirs(output_base, exist_ok=True)
            
            for rel_path in md_files:
                try:
                    full_input_path = os.path.join(temp_dir, rel_path)
                    with open(full_input_path, 'r', encoding='utf-8') as f:
                        original = f.read()
                    
                    translated = translate_content(original)
                    
                    full_output_path = os.path.join(output_base, rel_path)
                    os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
                    with open(full_output_path, 'w', encoding='utf-8') as f:
                        f.write(translated)
                    
                    task['progress']['completed'] += 1
                    # Artificial delay to avoid hammering the free tier
                    time.sleep(2) 
                except Exception as e:
                    logger.error(f"Failed to translate {rel_path}: {e}")
                    task['errors'].append({"file": rel_path, "error": str(e)})
            
            task['status'] = 'completed'
            task['output_path'] = output_base
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            task['status'] = 'failed'
            task['error'] = str(e)
        finally:
            shutil.rmtree(temp_dir)
            task_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

# --- Routes ---
@app.route('/translate-repo', methods=['POST'])
def start_translation():
    data = request.json
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'id': task_id,
        'owner': data.get('owner', 'scapedotes'),
        'repo': data.get('repo', 'Hermes-Wiki'),
        'branch': data.get('branch', 'master'),
        'status': 'pending',
        'progress': {'completed': 0, 'total': 0},
        'errors': [],
        'created_at': datetime.datetime.utcnow().isoformat()
    }
    task_queue.put(task_id)
    return jsonify({"task_id": task_id}), 202

@app.route('/task-status/<task_id>', methods=['GET'])
def get_status(task_id):
    return jsonify(tasks.get(task_id, {"error": "Not found"})), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
