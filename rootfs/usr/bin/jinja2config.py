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
import requests
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ThreadPoolExecutor

HASS_CONFIG_DIR = os.getenv('HASS_CONFIG_DIR')
CONFIG_FILE_NAME = 'jinja2config.yaml'
CONFIG_FILE_PATH = pathlib.Path(HASS_CONFIG_DIR) / CONFIG_FILE_NAME
CACHED_CONFIG_VARS = {}
CACHED_HA_ENTITIES = None
FILE_CONFIGS_KEY = '.file_configs'
SKIPPED_FILES_KEY = '.skipped_files'
HA_ENTITIES_KEY = 'ha_entities'

# Home Assistant API configuration
SUPERVISOR_TOKEN = os.getenv('SUPERVISOR_TOKEN')
HA_API_URL = 'http://supervisor/core/api'

def fetch_ha_entities():
    """Fetch all entities from Home Assistant API.
    
    Returns a dictionary with entity_id as keys and entity state objects as values.
    Returns None if the API is not accessible or an error occurs.
    """
    if not SUPERVISOR_TOKEN:
        print("Warning: SUPERVISOR_TOKEN not available, cannot fetch HA entities")
        return None
    
    try:
        headers = {
            'Authorization': f'Bearer {SUPERVISOR_TOKEN}',
            'Content-Type': 'application/json',
        }
        
        response = requests.get(
            f'{HA_API_URL}/states',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            entities = response.json()
            # Convert to a dictionary keyed by entity_id for easier access
            entity_dict = {entity['entity_id']: entity for entity in entities}
            print(f"Fetched {len(entity_dict)} entities from Home Assistant")
            return entity_dict
        else:
            print(f"Warning: Failed to fetch HA entities, status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Warning: Error fetching HA entities: {e}")
        return None
    except Exception as e:
        print(f"Warning: Unexpected error fetching HA entities: {e}")
        return None

def is_file_skipped(file_path: pathlib.Path) -> bool:
    """Check if a file should be skipped based on .skipped_files configuration.
    
    Returns True if the file should be skipped, False otherwise.
    The file path is relative to HASS_CONFIG_DIR.
    """
    if SKIPPED_FILES_KEY not in CACHED_CONFIG_VARS:
        return False
    
    skipped_files = CACHED_CONFIG_VARS[SKIPPED_FILES_KEY]
    if not isinstance(skipped_files, list):
        return False
    
    # Get the relative path from HASS_CONFIG_DIR
    try:
        relative_path = file_path.relative_to(HASS_CONFIG_DIR)
        relative_path_str = str(relative_path)
        
        # Check if this file is in the skipped list
        if relative_path_str in skipped_files:
            return True
    except ValueError:
        # File is not relative to HASS_CONFIG_DIR
        pass
    
    return False

def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override values taking precedence.
    
    Recursively merges nested dictionaries. Lists and other types are replaced, not merged.
    Returns a new dictionary without modifying the originals.
    """
    result = {}
    # Start with all keys from base
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = value.copy()
        else:
            result[key] = value
    
    # Apply overrides
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def get_variables_for_file(file_path: pathlib.Path) -> dict:
    """Get variables for a specific file, merging global and file-specific configs.
    
    Returns a deep merge of global variables with file-specific overrides.
    The file path is relative to HASS_CONFIG_DIR.
    """
    # Start with base config (excluding special keys)
    base_vars = {k: v for k, v in CACHED_CONFIG_VARS.items() 
                 if k not in (FILE_CONFIGS_KEY, SKIPPED_FILES_KEY)}
    
    # Add Home Assistant entities if available
    if CACHED_HA_ENTITIES is not None:
        base_vars[HA_ENTITIES_KEY] = CACHED_HA_ENTITIES
    
    # Check if there are file-specific configs
    if FILE_CONFIGS_KEY not in CACHED_CONFIG_VARS:
        return base_vars
    
    file_configs = CACHED_CONFIG_VARS[FILE_CONFIGS_KEY]
    if not isinstance(file_configs, dict):
        return base_vars
    
    # Get the relative path from HASS_CONFIG_DIR
    try:
        relative_path = file_path.relative_to(HASS_CONFIG_DIR)
        relative_path_str = str(relative_path)
        
        # Check if there's a config for this specific file
        if relative_path_str in file_configs:
            file_specific_config = file_configs[relative_path_str]
            if isinstance(file_specific_config, dict):
                print(f"Applying file-specific config for {relative_path_str}")
                return deep_merge(base_vars, file_specific_config)
    except ValueError:
        # File is not relative to HASS_CONFIG_DIR
        pass
    
    return base_vars

def load_config_variables():
    """Load variables from jinja2config.yaml and cache them. Also refresh HA entities."""
    global CACHED_CONFIG_VARS, CACHED_HA_ENTITIES
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
    
    # Refresh Home Assistant entities
    CACHED_HA_ENTITIES = fetch_ha_entities()

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
    try:
        os.remove(output_file)
    except FileNotFoundError:
        print(f"Output file {output_file} does not exist, skipping removal")
    except Exception as e:
        print(f"Error removing {output_file}: {e}")

def compile(file_path: pathlib.Path):
    # Check if this file should be skipped
    if is_file_skipped(file_path):
        relative_path = file_path.relative_to(HASS_CONFIG_DIR)
        print(f"Skipping {relative_path} (in .skipped_files)")
        return
    
    output_file = get_output_file(file_path)
    print(f"Compiling {file_path} to: {output_file}")
    error_log_file = file_path.parent / f"{file_path.name}.errors.log"
    result_content = f"# DO NOT EDIT: Generated from: {file_path.name}\n"
    
    # Get variables for this specific file (global + file-specific merged)
    file_vars = get_variables_for_file(file_path)
    
    # Create a temporary YAML file with the merged config variables for j2
    with tempfile.NamedTemporaryFile(mode='w+t', delete=False, suffix=".yaml") as vars_file:
        yaml.dump(file_vars, vars_file)
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
    """Find all .yaml.jinja template files in the config directory, excluding skipped files"""
    templates = []
    for root, _, files in os.walk(HASS_CONFIG_DIR):
        for file in files:
            if file.endswith('.yaml.jinja'):
                file_path = pathlib.Path(root) / file
                if not is_file_skipped(file_path):
                    templates.append(file_path)
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
                file_path = pathlib.Path(event.src_path)
                if not is_file_skipped(file_path):
                    QUEUE.append(ChangeRecorder(file_path))
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
    
    # Load config variables and fetch HA entities at startup
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