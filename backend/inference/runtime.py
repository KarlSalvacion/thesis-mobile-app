import os

from roboflow import Roboflow

from config.settings import ROBOFLOW_API_KEY, ROBOFLOW_PROJECT, ROBOFLOW_VERSION, ROBOFLOW_WORKSPACE, USE_LOCAL_INFERENCE

# Ensure the RF API key is in environment for any downstream SDKs.
if ROBOFLOW_API_KEY and not os.environ.get('ROBOFLOW_API_KEY'):
    os.environ['ROBOFLOW_API_KEY'] = ROBOFLOW_API_KEY

local_model = None
if USE_LOCAL_INFERENCE:
    try:
        print('Initializing local inference server...')
        from inference import get_model

        if ROBOFLOW_WORKSPACE:
            model_id = f'{ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT}/{ROBOFLOW_VERSION}'
        else:
            model_id = f'{ROBOFLOW_PROJECT}/{ROBOFLOW_VERSION}'
        local_model = get_model(model_id=model_id, api_key=ROBOFLOW_API_KEY)
        print(f'Local inference model loaded: {model_id}')
    except ImportError as e:
        print(f"Warning: Could not import 'inference' package: {e}")
        print('Install with: pip install inference')
        print('Falling back to Roboflow cloud API...')
    except Exception as e:
        print(f'Warning: Could not initialize local inference: {e}')
        print('Falling back to Roboflow cloud API...')

rf = Roboflow(api_key=ROBOFLOW_API_KEY)
try:
    ws = rf.workspace(ROBOFLOW_WORKSPACE) if ROBOFLOW_WORKSPACE else rf.workspace()
except Exception:
    ws = rf.workspace()
project = ws.project(ROBOFLOW_PROJECT)
model = project.version(ROBOFLOW_VERSION).model
