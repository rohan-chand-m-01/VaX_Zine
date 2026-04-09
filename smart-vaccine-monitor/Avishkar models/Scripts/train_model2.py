import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split
import joblib

# -----------------------------
# LOAD DATA
# -----------------------------

df = pd.read_csv("model2_predictor_data.csv")

X = df.drop("will_breach_10min", axis=1)
y = df["will_breach_10min"]

# -----------------------------
# TRAIN TEST SPLIT
# -----------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# -----------------------------
# MODEL
# -----------------------------

model = RandomForestClassifier(
    n_estimators=80,
    max_depth=10,
    class_weight="balanced",
    random_state=42
)

model.fit(X_train, y_train)

# Save model
joblib.dump(model, "predictor_model.pkl")

print("✅ Model 2 trained!")

# -----------------------------
# PREDICTION
# -----------------------------

y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

# -----------------------------
# EVALUATION
# -----------------------------

print("\n📊 Classification Report:")
print(classification_report(y_test, y_pred))

print("\n📊 Confusion Matrix:")
print(confusion_matrix(y_test, y_pred))

print("\n📊 ROC-AUC Score:")
print(roc_auc_score(y_test, y_prob))