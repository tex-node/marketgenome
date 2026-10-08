# Multi-asset studies operations

Create a study:

```powershell
market-genome studies create .\research\studies\multi_asset_episode_study_v1.yaml
market-genome studies preflight <study_id>
market-genome studies run-pilot <study_id>
market-genome studies run-validation <study_id>
market-genome studies lock-final-test <study_id>
market-genome studies run-final-test <study_id>
market-genome studies report <study_id>
```

Do not run final-test commands until validation selection is complete and the lock is intentional.

