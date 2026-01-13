#! /usr/bin/python3
import os
import sys
import signal
import pathlib
import subprocess
import time
import shutil
import tempfile
import yaml
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ThreadPoolExecutor

HASS_CONFIG_DIR = os.getenv('HASS_CONFIG_DIR')
CONFIG_FILE_NAME = 'jinja2config.yaml'
CONFIG_FILE_PATH = pathlib.Path(HASS_CONFIG_DIR) / CONFIG_FILE_NAME
CACHED_CONFIG_VARS = {}

def load_config_variables():
    """Load variables from jinja2config.yaml and cache them"""
    global CACHED_CONFIG_VARS
    if CONFIG_FILE_PATH.exists():
        try:
            with open(CONFIG_FILE_PATH, 'r') as f:
                config = yaml.safe_load(f)
                if isinstance(config, dict):
                    CACHED_CONFIG_VARS = config
                    print(f"Loaded {len(config)} variables from {CONFIG_FILE_NAME}")
                else:
                    print(f"Warning: {CONFIG_FILE_NAME} does not contain a dictionary")
                    CACHED_CONFIG_VARS = {}
        except yaml.YAMLError as e:
            print(f"Error parsing {CONFIG_FILE_NAME}: {e}")
            CACHED_CONFIG_VARS = {}
        except Exception as e:
            print(f"Error loading {CONFIG_FILE_NAME}: {e}")
            CACHED_CONFIG_VARS = {}
    else:
        print(f"{CONFIG_FILE_NAME} not found, using empty context")
        CACHED_CONFIG_VARS = {}

def check_dependencies():
    if not shutil.which('j2'):
        print("jinjanator must be installed: pip install jinjanator (https://github.com/kpfleming/jinjanator)")
        time.sleep(1)
        exit(1)
    if not shutil.which('prettier'):
        print("Prettier must be installed: apt-get install nodejs npm && npm install -g prettier")
        time.sleep(1)
        exit(1)

def get_output_file(file_path: pathlib.Path):
    output_file = file_path
    if output_file.suffix == '.jinja':
        output_file = output_file.with_suffix('')
    return output_file

def remove(file_path: pathlib.Path):
    output_file = get_output_file(file_path)
    print(f"{file_path} deleted, removing: {output_file}")
    os.remove(output_file)

def compile(file_path: pathlib.Path):
    output_file = get_output_file(file_path)
    print(f"Compiling {file_path} to: {output_file}")
    error_log_file = file_path.parent / f"{file_path.name}.errors.log"
    result_content = f"# DO NOT EDIT: Generated from: {file_path.name}\n"
    
    # Create a temporary YAML file with cached config variables for j2
    with tempfile.NamedTemporaryFile(mode='w+t', delete=False, suffix=".yaml") as vars_file:
        yaml.dump(CACHED_CONFIG_VARS, vars_file)
        vars_file_path = vars_file.name
    
    try:
        result = subprocess.run(['j2', '--customize', '/etc/jinja2config/j2_customizations.py', '--format', 'yaml', str(file_path), vars_file_path], capture_output=True)
    finally:
        # Clean up the temporary variables file
        if os.path.exists(vars_file_path):
            os.remove(vars_file_path)
    
    if result.returncode == 0:
        result_content += result.stdout.decode()
        if os.path.exists(error_log_file):
            os.remove(error_log_file)
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w+t', delete_on_close=False, suffix=".yaml") as f:
            f.write(result_content)
            f.flush()
            f.close()
            print(f"Using Prettier to formatting temp file '{f.name}' for '{output_file.name}'...")
            subprocess.run(['prettier', '--write', f.name, '--log-level', 'warn'])
            print(f"Copying temp file '{f.name}' to '{output_file}'...")
            shutil.copyfile(f.name, output_file)
    else:
        if output_file.exists():
            os.remove(output_file)
        print(f"Error compiling {file_path}!")
        with open(error_log_file, 'wb') as err_f:
            err_f.write(result.stderr)
        print(result.stderr.decode())

def recompile(file_path: pathlib.Path):
    print(f"Recompiling {file_path} due to changes")
    compile(file_path)

def find_all_jinja_templates():
    """Find all .yaml.jinja template files in the config directory"""
    templates = []
    for root, _, files in os.walk(HASS_CONFIG_DIR):
        for file in files:
            if file.endswith('.yaml.jinja'):
                templates.append(pathlib.Path(root) / file)
    return templates

@dataclass
class ChangeRecorder:
    path: pathlib.Path
    deleted: bool = False
    initial_compile: bool = False
    
QUEUE: list[ChangeRecorder] = []
WINDOW_START: float | None = None
SHUTDOWN = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global SHUTDOWN
    print(f"Received signal {signum}, initiating graceful shutdown...", file=sys.stderr)
    SHUTDOWN = True


class JinjaEventHandler(FileSystemEventHandler):
    def _handle(self, event):
        if not event.is_directory:
            if event.src_path.endswith('.yaml.jinja'):
                QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path)))
            elif event.src_path == CONFIG_FILE_NAME:
                self._recompile_all_templates()
                
    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path), deleted=True))

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.dest_path)))
        if not event.is_directory and event.src_path.endswith('.yaml.jinja'):
            QUEUE.append(ChangeRecorder(pathlib.Path(event.src_path), deleted=True))
    
    def _recompile_all_templates(self):
        """Recompile all templates when config file changes"""
        print(f"{CONFIG_FILE_NAME} changed, reloading variables and recompiling all templates...")
        load_config_variables()
        for template_path in find_all_jinja_templates():
            QUEUE.append(ChangeRecorder(template_path))

def process_change(change: ChangeRecorder):
    if change.deleted:
        remove(change.path)
    else:
        if change.initial_compile:
            compile(change.path)
        else:
            recompile(change.path)

def process_changes(changes: list[ChangeRecorder]):
    deduped = {}
    for change in changes:
        deduped[change.path] = change

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_change, change) for change in deduped.values()]
        for future in futures:
            future.result()

def main():
    global QUEUE, WINDOW_START, SHUTDOWN
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    check_dependencies()
    
    # Load config variables at startup
    load_config_variables()
    
    print(f"Compiling Jinja templates to YAML: {HASS_CONFIG_DIR}/**/*.yaml.jinja")
    for template_path in find_all_jinja_templates():
        QUEUE.append(ChangeRecorder(template_path, initial_compile=True))

    event_handler = JinjaEventHandler()
    observer = Observer()
    observer.schedule(event_handler, HASS_CONFIG_DIR, recursive=True)
    observer.start()

    try:
        while not SHUTDOWN:
            time.sleep(1)
            if QUEUE:
                if WINDOW_START is None:
                    WINDOW_START = time.time()
                elif time.time() - WINDOW_START > 5:
                    queue = QUEUE
                    QUEUE = []
                    process_changes(queue)
                    WINDOW_START = None
    finally:
        print("Stopping observer...", file=sys.stderr)
        observer.stop()
        observer.join()
        print("Observer stopped gracefully", file=sys.stderr)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)