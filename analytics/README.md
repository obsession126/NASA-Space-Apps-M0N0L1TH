# Analytics Module

This module runs a fully synthetic telemetry source, creates consistent measurement vectors, evaluates them against a synthetic baseline, and serves results to a local frontend through a JSON API and Server-Sent Events (SSE). Physical sensors, a database, and a medically validated model are not required. History is limited to the latest 500 events in process memory and is cleared when the service restarts.

## Run the service

From the repository root in Windows PowerShell:

```powershell
python -m venv analytics\.venv
.\analytics\.venv\Scripts\python.exe -m pip install -r analytics\requirements.txt
.\analytics\.venv\Scripts\python.exe -m analytics
```

By default, the service listens only on `127.0.0.1:8765`. After startup, it creates a synthetic baseline and runs the simulator at one event per second. Adjust the interval and generator seed for a slower or more illustrative stream:

```powershell
.\analytics\.venv\Scripts\python.exe -m analytics --interval 2 --seed 42 --scenario demo
```

Available modes are `demo`, `normal`, `interaction_shift`, `gradual_drift`, `sensor_artifact`, `signal_loss`, and `radiation_event`. The `demo` mode repeatedly switches between a stable baseline, nonlinear disagreement among signals, an artifact/low-quality reading, drift, signal loss, and a radiation event. The scenario is a synthetic simulator label; it is not passed to the model as a feature and is not a clinical label.

A local Next.js client can read the API at `http://127.0.0.1:8765`. If needed, allowed browser origins can be configured through the comma-separated `ANALYTICS_CORS_ORIGINS` variable. Do not expose the demo server to a public network without authentication, authorization, and appropriate data protection.

For a live dashboard, a client can subscribe to SSE:

```typescript
const stream = new EventSource("http://127.0.0.1:8765/api/v1/stream");
stream.addEventListener("telemetry", (message) => {
  const event = JSON.parse((message as MessageEvent<string>).data);
  // Update chart series from event.measured_at and event.measurements.
  // Render event.analysis.status, score, data_quality, and top_contributors.
});
```

For an initial UI load, call `GET /api/v1/snapshot`; for charts, call `GET /api/v1/history?limit=100`. Use `feature_names` with `feature_vector` for models or tables, or use `measurements[name]` for charts with labels and units. Do not interpret `analysis.status` as a clinical status.

## HTTP API

| Method and path | Purpose |
|---|---|
| `GET /healthz` | Check whether the process is available |
| `GET /api/v1/snapshot` | Service state, event count, and newest measurement with analysis |
| `GET /api/v1/history?limit=100` | Recent measurements; `limit` is constrained to 1-500 |
| `GET /api/v1/stream` | SSE `telemetry` events; each event has an `id` for resuming with `Last-Event-ID` |

The formal JSON Schema for a telemetry event is [event.schema.json](./event.schema.json). The positional `feature_vector` array is defined by the paired `feature_names` array; their order is part of the version `1.0` contract.

Illustrative `snapshot` excerpt (the `...` abbreviations are intentional; the complete valid event shape is defined by the JSON Schema):

```json
{
  "schema_version": "1.0",
  "service": {
    "status": "running",
    "source": "synthetic-simulator",
    "scenario_mode": "demo",
    "analysis_version": "nonlinear-ensemble-v1",
    "calibration": {
      "source": "synthetic-normal-baseline",
      "samples": 768,
      "medical_validation": false
    },
    "started_at": "2026-01-01T00:00:00Z"
  },
  "event_count": 1,
  "latest": {
    "schema_version": "1.0",
    "event_id": "crew-01-00000000",
    "measured_at": "2026-01-01T00:00:00Z",
    "recorded_at": "2026-01-01T00:00:00Z",
    "source": "synthetic-simulator",
    "is_synthetic": true,
    "feature_names": ["hr_bpm", "hrv_ms", "... 34 additional feature names"],
    "feature_vector": [77.1, 50.2, "... 34 additional values"],
    "measurements": {
      "hr_bpm": {
        "value": 77.1,
        "unit": "bpm",
        "quality": "good",
        "source": "simulated"
      },
      "...": "additional measurements follow the event.schema.json contract"
    },
    "context": {
      "profile_id": "crew-01",
      "mission_elapsed_min": 0,
      "mission_phase": "transit",
      "link_online": true,
      "simulation_scenario": "normal"
    },
    "analysis": {
      "status": "normal",
      "score": 0.41,
      "score_kind": "empirical_tail_rank_not_probability",
      "threshold": 0.99,
      "detector": "nonlinear-ensemble-v1",
      "explanation": "The vector did not exceed the demonstration threshold relative to the synthetic baseline.",
      "top_contributors": [],
      "data_quality": {
        "valid_fraction": 1.0,
        "missing_features": [],
        "low_quality_features": [],
        "status": "good"
      }
    }
  }
}
```

This excerpt is abbreviated. In a real response, `feature_names`, `feature_vector`, and `measurements` contain all 36 features in the registry. Each position in `feature_vector` corresponds to the field at the same index in `feature_names`. For charts, prefer `measurements`, keyed by feature name and unit. `measured_at` is the simulated measurement time; `recorded_at` is the time it was recorded. Missing data is represented by `null`, low quality by `quality: "low"`, and signal loss by `quality: "missing"`.

The possible `analysis.status` values are:

- `normal` — the vector did not exceed the demonstration threshold; this does not certify a normal health state.
- `anomaly_review` — the model identified an unusual combination that needs review.
- `data_quality_review` — a value is missing or low-quality, so the result must not be presented as confirmed normal.
- `insufficient_data` — too few valid features are available; `score` is `null`.

The `score` is an empirical tail rank of the joint maximum of Isolation Forest scores, conditional residuals from nonlinear models, and marginal deviations of individual signals, recalibrated on held-out synthetic examples. It is not a probability, diagnostic confidence, or universal risk metric. Cumulative dose is included in the vector and Isolation Forest, but is not scored as an isolated value because its normal range depends on mission duration. `threshold` is a demonstration setting, not a medical threshold. `top_contributors` lists deviating features and pairwise interactions; `deviation_magnitude` is a deviation in transformed feature space, not a probability or causal explanation.

## Personal trends and XGBoost

The DRF profile-insights API creates a separate one-step model for each feature using the profile's good-quality history. In newly recorded history, each observation is a separate event; after `compact_telemetry` runs, older data is represented by minute-level aggregate means. `XGBRegressor` forecasts the next observation for numeric channels. Categorical codes may use `XGBClassifier` when the history contains enough examples from multiple classes.

The numeric model is trained on the earlier 80% of the sequence, evaluated on the later chronological portion, and forecasts one next sample from the latest eight values and available mission context. For supported continuous sensor channels, an adaptive scalar Kalman filter denoises the historical input features; unusually large innovations receive a high gain so sustained or abrupt changes are not smoothed away. Forecast targets, stored measurements, and anomaly detection continue to use the original values. Categorical and self-reported channels are not filtered. The target is the next measurement value, not a medical state or synthetic scenario label. For numeric channels, the API returns a robust trend direction, forecast, number of values used, and median absolute error on the chronological holdout, plus metadata indicating whether input filtering was applied.

The model requires at least 36 good-quality observations for a channel. This is a sample-based forecast of one next record, not a forecast over a specific number of minutes or hours. Holdout error describes only the model's past errors on the available history; it is not a probability, confidence interval, or clinical uncertainty estimate. Categorical values with no variation and channels with insufficient history do not receive fabricated forecasts. Missing and low-quality values are excluded from the training sequence.

This is an experimental, profile-specific time-series model, not proven accuracy improvement or superiority over Apple Watch or other medical or consumer products. It has not been independently evaluated on real space telemetry. Astronaut selection, preparation, or ranking is not a goal of this system; high-stakes decisions about people require separate validated procedures and human oversight.

## Mathematical model

The analytics pipeline contains two separate models: an event-level anomaly detector and a profile-level, one-step trend forecaster. The Kalman filter is part of the forecaster's input preparation only; it is not applied to stored telemetry or to the anomaly detector.

### Kalman filtering for forecast inputs

For a supported sensor channel, let \(x_t\) be the \(t\)-th finite, good-quality measurement. The forecaster first requires at least 36 usable samples and robustly normalizes them:

$$
c = \operatorname{median}(x_{\text{train}}), \qquad
s = \max(1.4826\,\operatorname{MAD}(x_{\text{train}}),\,s_{\text{fallback}}), \qquad
z_t = \frac{x_t-c}{s}.
$$

Here, \(x_{\text{train}}\) is the prefix used for fitting (the training targets plus the eight observations needed to form their lag windows). The scale starts at \(1.4826\,\operatorname{MAD}\); if that is nearly zero, the implementation tries the interquartile range divided by 1.349, then \(\max(|c|10^{-6},10^{-6})\).

The filter is a scalar random-walk Kalman estimator. It estimates measurement-noise variance from the training prefix only:

$$
d_t = z_t-z_{t-1}, \qquad
\hat\sigma_d = \frac{1.4826\,\operatorname{MAD}(d)}{\sqrt{2}}, \qquad
R = \max(\hat\sigma_d^2,10^{-4}), \qquad Q=0.1R.
$$

The division by \(\sqrt{2}\) approximates the noise in a difference of two measurements. This is a robust heuristic, not a sensor-calibration measurement. With initial state \(\hat z_0=z_0\) and variance \(P_0=R\), each subsequent observation is processed as:

$$
\begin{aligned}
P_t^- &= P_{t-1}+Q, \\
e_t &= z_t-\hat z_{t-1}, \\
S_t &= P_t^-+R, \\
K_t &= P_t^-/S_t, \\
\hat z_t &= \hat z_{t-1}+K_t e_t, \\
P_t &= (1-K_t)P_t^-.
\end{aligned}
$$

To respond quickly to a large change, if \(|e_t|>3\sqrt{S_t}\), the implementation raises the gain to at least 0.85 before updating \(\hat z_t\). This reduces lag but does not decide whether a jump is a genuine change or an artifact; data-quality checks and the separate event detector remain important. Filtering is enabled only for the continuous sensor channels listed in `KALMAN_FILTER_FEATURES`; categorical and self-reported channels are not filtered.

### Per-feature XGBoost forecast

For a numeric channel, each supervised example predicts the next normalized **raw** measurement \(z_t\). Its input consists of the previous eight filtered values and the mission context recorded with the latest of those observations:

$$
\mathbf u_t =
[\hat z_{t-8},\ldots,\hat z_{t-1},\mathbf c_{t-1}],
\qquad
y_t=z_t.
$$

The filter changes \(\mathbf u_t\), not \(y_t\). Thus the model learns to forecast the observed measurement rather than a smoothed target, and holdout error is computed against unfiltered observations. The context contains available mission elapsed time, EVA/link state, activity intensity, and radiation dose rate, excluding the target channel itself. Missing context values are represented as `NaN`.

With \(N=n-8\) lagged examples, the chronological split point is \(k=\max(12,\lfloor0.8N\rfloor)\). The estimator is fitted on examples \(0,\ldots,k-1\); at least three later examples are required for a ready forecast. The numeric estimator is an XGBoost regression ensemble of 48 shallow trees (maximum depth 2), with squared-error objective, learning rate 0.05, and L2 regularization \(\lambda=5\):

$$
\hat f(\mathbf u)=\sum_{m=1}^{48}\eta f_m(\mathbf u), \qquad \eta=0.05.
$$

The reported chronological holdout error is the median absolute error converted back to the channel's original units:

$$
\operatorname{MedAE}
= s\,\operatorname{median}_{t\in\mathrm{holdout}}
\left|\hat f(\mathbf u_t)-z_t\right|.
$$

The next-sample forecast is similarly converted back as \(\hat x_{n+1}=c+s\hat z_{n+1}\). It is one sample ahead, not a fixed-time or clinical forecast.

The reported trend direction is calculated separately from the last 12 **raw** values so that smoothing does not hide a shift. It uses the median of all pairwise slopes (a robust Theil–Sen-style slope), \(b=\operatorname{median}_i(x_i-\beta i)\), residuals \(r_i=x_i-(b+\beta i)\), and robust noise \(\sigma_r=1.4826\,\operatorname{MAD}(r)\). Its normalized trend is \(\beta(n-1)/\sigma_r\); values at least 0.75 are labeled `rising`, at most -0.75 `falling`, and otherwise `stable`. A small numerical floor is used when the residual noise is zero.

Categorical channels do not use the Kalman filter or the numeric regressor. When a categorical history has at least two training classes, an XGBoost classifier predicts the next category from the previous eight category codes and mission context; a single-class history receives no fabricated forecast.

### Event-level anomaly score

The anomaly detector is separate from the forecast model. It is calibrated on synthetic baseline vectors. With the default 768 baseline vectors, a deterministic permutation allocates the first 384 to fit the conditional models, the next 192 to fit the Isolation Forest, and the final 192 to calibrate component scales and the empirical score distribution. For a 36-dimensional event vector \(\mathbf x\), a `RobustScaler` first centers each feature by its median and scales it by its 10th-to-90th percentile range. A degree-two polynomial expansion adds squares and pairwise products. The resulting 702 polynomial features are combined with five conditional residual features.

For five selected channels \(j\), a random forest with 96 trees predicts that channel from its related predictors (minimum leaf size 8):

| Target | Predictors |
|---|---|
| Heart rate | Activity intensity, movement RMS, activity duration |
| HRV | Heart rate, activity intensity, sleep duration |
| Respiratory rate | Heart rate, activity intensity, movement RMS |
| SpO2 | Respiratory rate, O2 fraction, radiation dose rate |
| Sleep quality | Sleep duration, awakenings, self-reported stress |

The residual is \(r_j=x_j-\hat x_j\), scaled by \(\max(1.4826\,\operatorname{MAD}(r_j),0.25)\). In parallel, an Isolation Forest with 160 trees scores the expanded vector (the detector uses \(-\texttt{score\_samples}\), so larger values mean more unusual). A univariate component takes the largest robust marginal deviation; cumulative radiation dose is excluded from that component because its expected value depends on mission duration.

For each component \(v\), calibration computes its median \(m_v\) and robust scale \(s_v=\max(1.4826\,\operatorname{MAD}(v),10^{-6})\). For a new event, the standardized components are \(a_v=(v-m_v)/s_v\). The combined score before percentile calibration is:

$$
A(\mathbf x)=\max\left(
a_{\mathrm{forest}},
a_{\mathrm{conditional}},
a_{\mathrm{univariate}}
\right).
$$

The returned score is the empirical percentile of \(A(\mathbf x)\) among calibration scores \(A_1,\ldots,A_m\):

$$
\operatorname{score}(\mathbf x)
=\frac{1}{m}\sum_{i=1}^{m}\mathbf 1[A_i\le A(\mathbf x)].
$$

The default review threshold is 0.99. This percentile is not a probability or a medical risk. If less than 80% of the 36 fields are usable, the detector returns `insufficient_data` instead of a score; otherwise, missing or low-quality raw values are replaced with the robust scaler's center for model computation and remain explicitly marked in the data-quality result.

All of these equations describe the current software behavior, not a clinically validated model. The simulator and calibration data are synthetic, and improved real-world forecast accuracy has not yet been established.

## Feature vector

The canonical source for vector order, names, categories, and units is `analytics/contracts.py`, which corresponds to the [candidate parameter catalog](./PARAMETER_CATALOG.md). The vector includes:

- Cardiovascular signals: heart rate, HRV (RMSSD in the simulator), blood pressure, and a simulated ECG-derived RR interval.
- Respiration, SpO2, and skin temperature.
- Sleep, activity type/duration/intensity, movement, and self-reported symptom category/severity, stress, mood, and alertness.
- Dosimetry and cabin conditions: temperature, pressure, humidity, lighting, noise, CO2, and O2.
- Longitudinal/research fields, nutrition, and hydration.

Values named `*_index`, ECG-derived, Lab, and OCT are synthetic numeric proxies for testing data flow and interactions only. They are not real clinical measurements. Raw ECG, diagnostic thresholds, structured laboratory panels, and validated OCT results require separate formats and sources.

Mission identifiers and context are outside the vector: phase, EVA, communications status, event/countermeasure, and scenario label. They may be displayed or used for filtering and temporal explanation; the model does not use the scenario or ground-truth label.

## How detection works

1. At startup, the generator creates 768 synthetic baseline examples and deterministically shuffles them with a fixed seed so that all subsets contain different simulator time phases. Half are used for conditional models, one quarter for Isolation Forest, and the final quarter is an independent clean calibration set. They contain no disease labels and do not establish medical validity.
2. `RobustScaler` normalizes numeric fields with different units. Separate random forests predict expected heart rate, HRV, respiratory rate, SpO2, and sleep quality from their context; conditional residuals are evaluated against a separate portion of the clean synthetic baseline.
3. `PolynomialFeatures(degree=2)` adds squared and pairwise interaction features, and Isolation Forest scores unusual full expanded vectors relative to synthetic calibration examples. Individual signal deviations are scored separately. The maximum of all three components is recalibrated on the held-out sample to control the combined threshold. Cumulative dose is not evaluated separately from mission duration. The model is not trained online on incoming events, so it cannot learn anomalous simulations as normal.
4. The explanation layer returns the most deviant univariate, pairwise, and conditional features. Signal quality is assessed separately: low-quality features are not used as normal values, and the model does not return a score when there are substantial missing values.

The event-level detector and profile-level XGBoost trend forecaster are separate layers. The detector analyzes each event relative to the synthetic baseline; profile insights use XGBoost to forecast the next value of each channel from that profile's history.

The model detects differences from a limited synthetic distribution. It cannot guarantee detection of all hidden dependencies, is not clinically trained, and must not be used to diagnose or make treatment decisions. Gradient boosting is not used for anomaly detection: without independently validated labels, a classifier would learn simulator labels rather than establish real-world usefulness.

## Checks

```powershell
.\analytics\.venv\Scripts\python.exe -m unittest discover -s analytics\tests -v
```

Tests check completeness and ordering of the contract, a multidimensional scenario with a broken interaction, handling of quality/missing data, and HTTP responses. These tests validate software behavior on synthetic data; they are not medical validation.
