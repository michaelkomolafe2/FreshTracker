# FreshTracker grocery-category classifier

## Model overview

FreshTracker predicts a grocery category from the free-text ingredient name
entered by a user. The model is intended to reduce data-entry effort; its output
is a suggestion and is not suitable for safety, allergy, nutrition, or medical
decisions.

## Architecture

The persisted scikit-learn `Pipeline` combines:

1. A TF-IDF vectorizer using lowercase word unigrams and bigrams.
2. A Multinomial Naive Bayes classifier.

Training uses the fixed `random_state` value `42` and a stratified 80/20
train/test split so repeated runs against the same dependency versions and
dataset are reproducible.

## Training data

The source is `grocery_data.csv`. Blank names/categories and rows missing either
required value are removed before splitting. The generated `metrics.json` is the
source of truth for the evaluated row count and split ratio.

## Evaluation metrics

Running `python train_model.py` writes the complete current evaluation to
`metrics.json`, including:

- Dataset row count
- Train/test split ratio
- Overall holdout accuracy
- Per-class precision, recall, F1 score, and support from
  `sklearn.metrics.classification_report`

The checked-in metrics correspond to the checked-in model and dataset. They
must be regenerated together whenever training data or model code changes.

Current values pulled from `metrics.json`:

| Metric | Value |
| --- | ---: |
| Evaluated dataset rows | 150 |
| Train/test split | 80% / 20% |
| Overall accuracy | 56.67% |
| Macro-average precision | 64.03% |
| Macro-average recall | 55.83% |
| Macro-average F1 | 52.32% |
| Weighted-average F1 | 50.59% |

Produce recall and F1 are both 0% on the current 30-row holdout. This is a
release-blocking quality signal for any workflow that treats predictions as
authoritative; the current product must keep the result editable and should
collect more representative labeled examples before relying on automation.

## Known failure modes

- Brand and product names with no ingredient terms may be assigned to a
  superficially similar category.
- Regional ingredient names, spellings, and transliterations absent from the
  training data can be misclassified.
- Ambiguous names such as “cream,” “roll,” or “greens” lack enough context for
  reliable classification.
- Mixed products and prepared meals can reasonably belong to several
  categories, while the model returns only one.
- Misspellings, abbreviations, quantities, packaging text, and non-English
  input can reduce TF-IDF overlap with the training vocabulary.
- Rare categories with few examples have less reliable metrics and can be
  overwhelmed by better-represented classes.

## Data drift and retraining

Review production corrections and category frequencies monthly. Retrain at
least quarterly, and sooner when a category taxonomy changes, a material new
regional/product vocabulary appears, or monitored accuracy/correction rates
degrade. Every retraining run must regenerate `model.pkl` and `metrics.json`,
compare per-class metrics with the previous release, and receive review before
deployment.
