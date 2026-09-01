import importlib.util
import json
from pathlib import Path

import joblib
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline


SCRIPT_PATH = Path(__file__).with_name("train_model.py")


def load_train_model_module():
    spec = importlib.util.spec_from_file_location("train_model", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_grocery_data_requires_expected_columns(tmp_path):
    train_model = load_train_model_module()
    csv_path = tmp_path / "missing_category.csv"
    pd.DataFrame({"ingredient_name": ["milk"]}).to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Missing required column"):
        train_model.load_grocery_data(csv_path)


def test_train_and_evaluate_returns_fitted_pipeline_and_metrics():
    train_model = load_train_model_module()
    data = train_model.load_grocery_data(Path(__file__).with_name("grocery_data.csv"))

    pipeline, metrics = train_model.train_and_evaluate(data)

    assert isinstance(pipeline, Pipeline)
    assert metrics["dataset_row_count"] == len(data)
    assert metrics["train_test_split_ratio"] == {"train": 0.8, "test": 0.2}
    assert 0.0 <= metrics["overall_accuracy"] <= 1.0
    assert "accuracy" in metrics["classification_report"]
    assert pipeline.predict(["whole milk"])[0] in set(data["category"])


def test_save_model_writes_joblib_file(tmp_path):
    train_model = load_train_model_module()
    data = train_model.load_grocery_data(Path(__file__).with_name("grocery_data.csv"))
    pipeline, metrics = train_model.train_and_evaluate(data)
    model_path = tmp_path / "model.pkl"
    metrics_path = tmp_path / "metrics.json"

    train_model.save_model(pipeline, model_path)
    train_model.save_metrics(metrics, metrics_path)

    loaded_model = joblib.load(model_path)
    assert loaded_model.predict(["orange juice"])[0] == pipeline.predict(
        ["orange juice"]
    )[0]
    assert json.loads(metrics_path.read_text(encoding="utf-8")) == metrics
