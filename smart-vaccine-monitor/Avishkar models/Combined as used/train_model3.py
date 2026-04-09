import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.model_selection import train_test_split
import joblib

# -----------------------------
# LOAD DATA
# -----------------------------

df = pd.read_csv("model3_potency_data.csv")

X = df.drop("potency_pct", axis=1)
y = df["potency_pct"]

# -----------------------------
# TRAIN TEST SPLIT
# -----------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# -----------------------------
# MODEL
# -----------------------------

model = LinearRegression()
model.fit(X_train, y_train)

# Save model
joblib.dump(model, "potency_model.pkl")

print("✅ Model 3 trained!")

# -----------------------------
# PREDICTION
# -----------------------------

y_pred = model.predict(X_test)

# -----------------------------
# EVALUATION
# -----------------------------

print("\n📊 R² Score:")
print(r2_score(y_test, y_pred))

print("\n📊 Mean Absolute Error:")
print(mean_absolute_error(y_test, y_pred))