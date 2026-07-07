import json
import os
import glob
import uuid
import shutil
from flask import Flask, request, jsonify, render_template, send_from_directory
from openai import OpenAI

# --- ASK FOR ENDPOINT BEFORE STARTING ---
print("=" * 50)
print("  Chat AI - Local Client")
print("=" * 50)
KAGGLE_URL = input(" Enter the endpoint URL (e.g. https://your-url.trycloudflare.com/v1): ").strip()
if not KAGGLE_URL:
    print(" Error: No valid URL provided.")
    exit(1)
if not KAGGLE_URL.endswith("/v1"):
    if KAGGLE_URL.endswith("/"):
        KAGGLE_URL += "v1"
    else:
        KAGGLE_URL += "/v1"

MODELO = input(" Model name (default: CODER): ").strip() or "CODER"
print(f" Endpoint: {KAGGLE_URL}")
print(f" Model:   {MODELO}")
print("=" * 50)
print()

app = Flask(__name__)
client = OpenAI(base_url=KAGGLE_URL, api_key="kaggle")

# Upload folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Text extensions we can read
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.cpp', '.h', '.hpp',
    '.java', '.kt', '.go', '.rs', '.rb', '.php', '.swift', '.dart',
    '.html', '.htm', '.css', '.scss', '.sass', '.less',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.txt', '.md', '.rst', '.log', '.csv', '.sql', '.sh', '.bash',
    '.zsh', '.fish', '.ps1', '.bat', '.cmd', '.makefile',
    '.dockerfile', '.gitignore', '.env', '.editorconfig',
    '.vue', '.svelte', '.astro',
    '.lua', '.r', '.m', '.pl', '.ex', '.exs', '.erl',
    '.proto', '.graphql', '.tf', '.hcl',
    '.pyw', '.pyx', '.pxd', '.pxi',
}

messages = [{
    "role": "system",
    "content": "You are an expert software engineer. You have access to local files. Be concise and precise. When the user attaches files, analyze their content and respond about them."
}]

# --- TOOLS ---
def find_path(glob_pattern):
    return glob.glob(glob_pattern, recursive=True)

def read_file(path):
    if not os.path.exists(path):
        return f"Error: File '{path}' does not exist."
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            return content[:10000] if len(content) > 10000 else content
    except Exception as e:
        return f"Error reading {path}: {str(e)}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "find_path",
            "description": "Search for local files using glob patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "glob": {"type": "string", "description": "Glob pattern, e.g.: '**/*.py'"}
                },
                "required": ["glob"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a local file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"]
            }
        }
    }
]

def ejecutar_herramienta(nombre, args):
    if nombre == "find_path":
        return find_path(args.get("glob", "*"))
    elif nombre == "read_file":
        return read_file(args.get("path", ""))
    return f"Unknown tool: {nombre}"

def procesar_respuesta():
    global messages
    tool_calls_info = []
    while True:
        response = client.chat.completions.create(
            model=MODELO,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        msg = response.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content, tool_calls_info
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except:
                args = {}
            result = ejecutar_herramienta(name, args)
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": name,
                "content": str(result)
            })
            tool_calls_info.append({
                "name": name,
                "args": args,
                "result_preview": str(result)[:200] + ("..." if len(str(result)) > 200 else "")
            })

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    global messages
    user_message = request.form.get('message', '').strip()
    files = request.files.getlist('files')

    if not user_message and not files:
        return jsonify({"error": "Empty message and no files"}), 400

    content_parts = []

    if user_message:
        content_parts.append(user_message)

    file_infos = []

    for f in files:
        if not f.filename:
            continue

        ext = os.path.splitext(f.filename)[1].lower()
        safe_name = uuid.uuid4().hex + ext
        save_path = os.path.join(UPLOAD_FOLDER, safe_name)
        f.save(save_path)
        file_size = os.path.getsize(save_path)

        file_info = {
            "name": f.filename,
            "saved_name": safe_name,
            "size": file_size,
            "size_text": format_size(file_size),
            "path": save_path,
            "is_text": ext in TEXT_EXTENSIONS
        }
        file_infos.append(file_info)

        if ext in TEXT_EXTENSIONS:
            try:
                with open(save_path, 'r', encoding='utf-8', errors='ignore') as rf:
                    file_content = rf.read()
                if len(file_content) > 15000:
                    file_content = file_content[:15000] + "\n\n... [file truncated, use read_file to read in full]"
                content_parts.append(f'[Attached file: {f.filename} ({format_size(file_size)})]\n```\n{file_content}\n```')
            except Exception as e:
                content_parts.append(f'[Attached file: {f.filename} ({format_size(file_size)}) — Error reading: {str(e)}]')
        else:
            content_parts.append(f'[Attached file: {f.filename} ({format_size(file_size)}, binary type, saved to {save_path})]')

    full_content = '\n\n'.join(content_parts)
    messages.append({"role": "user", "content": full_content})

    try:
        respuesta, tool_info = procesar_respuesta()
        return jsonify({
            "response": respuesta,
            "tool_calls": tool_info,
            "files": file_infos
        })
    except Exception as e:
        if messages and messages[-1]["role"] == "user":
            messages.pop()
        return jsonify({"error": str(e)}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/reset', methods=['POST'])
def reset():
    global messages
    messages = [{
        "role": "system",
        "content": "You are an expert software engineer. You have access to local files. Be concise and precise. When the user attaches files, analyze their content and respond about them."
    }]
    for f in os.listdir(UPLOAD_FOLDER):
        fp = os.path.join(UPLOAD_FOLDER, f)
        if os.path.isfile(fp):
            os.remove(fp)
    return jsonify({"status": "history cleared"})

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, host='127.0.0.1', port=5000)
