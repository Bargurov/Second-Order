# I2A response substrate - coverage and integrity (Mission I)

Contract: `i2a-response-substrate-v1`, executing the locked i0-v1 protocol over the I1 candidate universe. This report accounts for coverage, failures, and basis provenance ONLY. It contains no event-versus-reference comparison, no estimand computation, no ranking, and no interpretation; those belong to later slices under the frozen protocol.

## Symmetric path statement

Every record - study event and ordinary reference alike - was computed by `compute_membership_records`, one shared boundary over the shipped event-study gate under the frozen F3 basis policy (adjusted/adjusted preferred, matched raw/raw disclosed fallback, never cross-basis). Membership is metadata, not mathematics; the symmetry is regression-tested (identical values and identical failures for identical inputs).

Readiness is per horizon: each requested response window (1d, 5d, 20d) is judged on its own forward tail, so a 1d or 5d response never depends on 20d availability. The 60-session estimation requirement, the interior-gap guard, and the basis policy are unchanged; each horizon is requested from the shipped gate individually.

## Denominator reconciliation

| family | event identities | reference attempts (per horizon) | distinct reference anchors | register/event overlap |
|---|---|---|---|---|
| FOMC | 65 | 1d: 1816 / 5d: 1299 | 1816 | 0 |
| OPEC | 32 | 1d: 1903 / 5d: 1631 / 20d: 889 | 1903 | 0 |

The FOMC event denominator is 65 and the OPEC study denominator is 32, exactly the frozen ledgers; reference attempts equal the I1 manifests (drift raises before any record is built). The OPEC known-date register remains exclusion-only: zero of its non-study dates appear in event membership. The FOMC 20d primary cell is structurally infeasible and has no substrate.

## Coverage and basis provenance (family x membership x horizon x metric)

| family | membership | h | metric | attempted | available | adjusted | raw fallback | unavailable |
|---|---|---|---|---|---|---|---|---|
| FOMC | event | 1d | raw_return | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 1d | spy_relative_ar | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 1d | sector_relative_ar | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 1d | sar | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 5d | raw_return | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 5d | spy_relative_ar | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 5d | sector_relative_ar | 65 | 65 | 65 | 0 | 0 |
| FOMC | event | 5d | sar | 65 | 65 | 65 | 0 | 0 |
| FOMC | reference | 1d | raw_return | 1816 | 1816 | 1816 | 0 | 0 |
| FOMC | reference | 1d | spy_relative_ar | 1816 | 1816 | 1816 | 0 | 0 |
| FOMC | reference | 1d | sector_relative_ar | 1816 | 1816 | 1816 | 0 | 0 |
| FOMC | reference | 1d | sar | 1816 | 1816 | 1816 | 0 | 0 |
| FOMC | reference | 5d | raw_return | 1299 | 1299 | 1299 | 0 | 0 |
| FOMC | reference | 5d | spy_relative_ar | 1299 | 1299 | 1299 | 0 | 0 |
| FOMC | reference | 5d | sector_relative_ar | 1299 | 1299 | 1299 | 0 | 0 |
| FOMC | reference | 5d | sar | 1299 | 1299 | 1299 | 0 | 0 |
| OPEC | event | 1d | raw_return | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 1d | spy_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 1d | sector_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 1d | sar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 5d | raw_return | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 5d | spy_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 5d | sector_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 5d | sar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 20d | raw_return | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 20d | spy_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 20d | sector_relative_ar | 32 | 32 | 32 | 0 | 0 |
| OPEC | event | 20d | sar | 32 | 32 | 32 | 0 | 0 |
| OPEC | reference | 1d | raw_return | 1903 | 1903 | 1903 | 0 | 0 |
| OPEC | reference | 1d | spy_relative_ar | 1903 | 1903 | 1903 | 0 | 0 |
| OPEC | reference | 1d | sector_relative_ar | 1903 | 1903 | 1903 | 0 | 0 |
| OPEC | reference | 1d | sar | 1903 | 1903 | 1903 | 0 | 0 |
| OPEC | reference | 5d | raw_return | 1631 | 1631 | 1631 | 0 | 0 |
| OPEC | reference | 5d | spy_relative_ar | 1631 | 1631 | 1631 | 0 | 0 |
| OPEC | reference | 5d | sector_relative_ar | 1631 | 1631 | 1631 | 0 | 0 |
| OPEC | reference | 5d | sar | 1631 | 1631 | 1631 | 0 | 0 |
| OPEC | reference | 20d | raw_return | 889 | 889 | 889 | 0 | 0 |
| OPEC | reference | 20d | spy_relative_ar | 889 | 889 | 889 | 0 | 0 |
| OPEC | reference | 20d | sector_relative_ar | 889 | 889 | 889 | 0 | 0 |
| OPEC | reference | 20d | sar | 889 | 889 | 889 | 0 | 0 |

## Failure accounting

- none: every attempted record is available (the era sits fully inside the price frame, so the I1 gates already guaranteed computability).

## Reproducibility posture

Event universes and the I1 manifests are deterministic from tracked artifacts; response extraction additionally requires the LOCAL gitignored price substrate (read-only; no provider fetch; missing cache fails loudly). Full fresh-clone execution is therefore not claimed. The in-memory substrate is uncurated and deterministically ordered; no response value is duplicated into this report.

## Reproduction

```
python -m scripts.i2a_response_substrate --emit
python -m unittest tests.test_i2a_response_substrate
```
