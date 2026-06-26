import pickle

p = r"C:\Users\CromptonConceptsLabs\tmr_profiles.pkl"
with open(p, "rb") as f:
    obj = pickle.load(f)

print(type(obj))
if isinstance(obj, dict):
    print(list(obj.keys()))
    if "test" in obj:
        print(type(obj["test"]))
        if isinstance(obj["test"], dict):
            print(list(obj["test"].keys()))
else:
    print("not-dict")
