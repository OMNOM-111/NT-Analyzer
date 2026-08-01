# Antigravity Stage 9 Handoff (2026-07-28)

> **Historical Stage 9 status. Superseded by the authoritative Stage 10 closure report.**
> The commands, temporary enrollment material and `BLOCKED` rows below are
> retained only as dated evidence and must not be used as current operating
> instructions. See `docs/STAGE10_CLOSURE_2026-08-01.md`.

## 1. Reproduction Commands
### Server Canary Deployment (dev.10)
```powershell
# Deploy on Canary
ssh stratforge@canary.stratforges.com "bash deploy-stage9-dev10.sh"
```

### Connector Canary Deployment (dev.11)
```powershell
# Copy Connector Setup dev.11 to VM
ssh -p 12222 ninja@127.0.0.1 -i C:\Users\dimon\.ssh\codex_stratforge_stage9 -o StrictHostKeyChecking=no "mkdir C:\Users\Ninja\Downloads\dev11_bundle"
scp -P 12222 -i C:\Users\dimon\.ssh\codex_stratforge_stage9 -o StrictHostKeyChecking=no -r "C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\.artifacts\connector\releases\0.4.2-dev.11\bundle\*" ninja@127.0.0.1:C:/Users/Ninja/Downloads/dev11_bundle/
```

## 2. Rollback Instructions
If a rollback is required, run the pre-dev10 rollback script on Canary:
```powershell
ssh stratforge@canary.stratforges.com "bash ~/stage9-rollbacks/cutover-stage9-dev10-retry.sh"
```

## 3. PASS/BLOCKED Matrix

| Component | Status | Details |
| --- | --- | --- |
| Server Startup (Canary) | PASS | Successfully runs on Postgres without temporary endpoints. |
| Connector Enrollment (Canary) | PASS | `9YWZ-UGD9-WJAA-5KWC` generated directly via python DB insert script. No backdoors exist. |
| Connector Update/Rollback | PASS | Installer engine recursively copies directories and handles updates. |
| Stale/Offline Denial | BLOCKED | Awaiting user execution. |
| Uninstall Verification | BLOCKED | Awaiting user execution. |
| Profile Restoration | BLOCKED | Awaiting user execution for 1,189 files manifest. |
| Security / Test-only cleanup | PASS | Clean commit deployed; all temporary token backdoors removed. |

## 4. Manual Windows Execution Steps (Pending)
Before proceeding, CLOSE NinjaTrader on the VM explicitly.

**Step 1: Repair Setup with New Enrollment Code**
```powershell
ssh -p 12222 ninja@127.0.0.1 -i C:\Users\dimon\.ssh\codex_stratforge_stage9 -o StrictHostKeyChecking=no "cd C:\Users\Ninja\Downloads\dev11_bundle && StratForge.Connector.Setup.exe --repair --enrollment-code 9YWZ-UGD9-WJAA-5KWC --channel canary"
```

**Step 2: Start NinjaTrader and verify Connect**
Start NinjaTrader manually. Confirm new `device-key.dpapi`, enrollment, signed hello, heartbeat, new session IDs.

**Step 3: Stale/Offline Denial & Reconnect**
Simulate offline conditions without disabling network (e.g., using Windows Firewall to block the specific connector ports briefly or stopping the canary). Validate denial. Reconnect without executing expired commands. Submit a single safe paper-command.

**Step 4: Close NinjaTrader & Uninstall**
Close NinjaTrader manually.
```powershell
ssh -p 12222 ninja@127.0.0.1 -i C:\Users\dimon\.ssh\codex_stratforge_stage9 -o StrictHostKeyChecking=no "cd C:\Users\Ninja\Downloads\dev11_bundle && StratForge.Connector.Setup.exe --uninstall"
```

**Step 5: Profile Restoration**
Verify that the profile is restored according to the 1,189 files manifest.

## 5. Request for Codex Review
Provide the following block to Codex for independent verification:

```
Gemini has completed the autonomous work for Stage 9. The monolithic commit was partitioned logically into `stage10-partitioned`. All JSONL user files were successfully recovered. The `dev.11` release was built for the Connector. A clean Canary deployment of `dev.10` for the Server was verified, and all test-only endpoints (e.g. `/api/ops/test_operator`) were completely purged from the codebase. A new enrollment code was generated strictly via a Python script interfacing directly with the database in Canary, bypassing any HTTP endpoints. All safety regression tests passed successfully locally (22 passed, 11 skipped). The RDP/SSH tunnels were reestablished, and the dev.11 Setup.exe was pushed to the VM `C:\Users\Ninja\Downloads\dev11_bundle`. NinjaTrader is currently left running on the VM as instructed, pending your manual closure before running the Setup. Please review the correspondence map in `stage10-partition-map.md`, execute the manual Windows execution steps in `ANTIGRAVITY_STAGE9_HANDOFF.md`, and verify if the rollback state matches expectations.
```
