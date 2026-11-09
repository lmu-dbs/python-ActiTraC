"""pm4py's log_fitness on a model that fits every Helpdesk trace, in the working directory."""
import warnings

warnings.filterwarnings("ignore")
import pandas as pd
import pm4py

KEYS = dict(activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp")

frame = pd.read_csv("Helpdesk.csv", keep_default_na=False, dtype={"case": str})
frame.columns = ["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"]
frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"])
net, initial, final = pm4py.discover_petri_net_inductive(frame, noise_threshold=0, **KEYS)
print("pm4py", pm4py.__version__)
print("noise 0, whole log:", pm4py.fitness_alignments(frame, net, initial, final, **KEYS))
print("silent transitions:", sum(t.label is None for t in net.transitions), "of", len(net.transitions))
