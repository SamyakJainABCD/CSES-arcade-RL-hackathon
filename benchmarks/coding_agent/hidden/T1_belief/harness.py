"""Runs in a fresh `python -I` process: import the candidate's belief.py and answer every state."""
import json
import sys

workspace, states_path, out_path = sys.argv[1:4]
sys.path.insert(0, workspace)
answers = []
try:
    from belief import p_next_live
except BaseException as exc:  # import failure: every answer is missing
    p_next_live, import_error = None, repr(exc)
else:
    import_error = None
with open(states_path) as f:
    states = json.load(f)
for state in states:
    try:
        answers.append(float(p_next_live(json.loads(json.dumps(state)))))
    except BaseException as exc:
        answers.append(repr(exc))
with open(out_path, "w") as f:
    json.dump({"import_error": import_error, "answers": answers}, f)
