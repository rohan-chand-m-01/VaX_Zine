import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, confusion_matrix
import joblib

# -----------------------------
# LOAD DATA
# -----------------------------

train_df = pd.read_csv("model1_normal_data.csv")
full_df  = pd.read_csv("synthetic_data.csv")

features = ["temp", "humidity", "temp_delta", "unsafe_mins"]

X_train = train_df[features]
X_test  = full_df[features]

y_true  = full_df["anomaly_flag"]

# -----------------------------
# TRAIN MODEL
# -----------------------------

model = IsolationForest(
    contamination=0.045,
    n_estimators=100,
    random_state=42
)

model.fit(X_train)

joblib.dump(model, "anomaly_model.pkl")

print("✅ Model trained!")

# -----------------------------
# PREDICT
# -----------------------------

y_pred = model.predict(X_test)

# Convert: 1 → normal (0), -1 → anomaly (1)
y_pred = [1 if x == -1 else 0 for x in y_pred]

# -----------------------------
# EVALUATION
# -----------------------------

print("\n📊 Classification Report:")
print(classification_report(y_true, y_pred))

print("\n📊 Confusion Matrix:")
print(confusion_matrix(y_true, y_pred))