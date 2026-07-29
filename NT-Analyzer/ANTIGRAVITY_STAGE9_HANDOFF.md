# Antigravity Stage 9 Handoff (2026-07-28)

## 1. Reproduction Commands
### Server Canary Deployment (dev.10)
```powershell
# Upload Server Release to Canary
scp .artifacts\server\releases\0.9.0-dev.10\StratForge.Server-0.9.0-dev.10-development.zip stratforge@canary.stratforges.com:~/
# Deploy on Canary
ssh stratforge@canary.stratforges.com "bash deploy-stage9-dev10.sh"
```

### Connector Canary Deployment (dev.10)
```powershell
# Upload Connector Release to Canary
scp .artifacts\connector\releases\0.4.2-dev.10\StratForge.Connector-0.4.2-dev.10-canary.zip stratforge@canary.stratforges.com:~/
```

### NinjaTrader VM Enrollment & Acceptance
```powershell
# Run Repair and Enrollment
ssh Ninja@VMNINJA "powershell -Command `"& 'C:\Users\Ninja\Downloads\Setup.exe' --repair --pairing-uri 'stratforge-connector://enroll?code=TOKEN&protocol=1.0' --server-origin 'https://canary.stratforges.com' --channel 'canary' --non-interactive`""
```

## 2. Rollback Instructions
If a rollback is required, run the pre-dev10 rollback script on Canary:
```powershell
ssh stratforge@canary.stratforges.com "bash ~/stage9-rollbacks/cutover-stage9-dev10-retry.sh"
```
On the VM, uninstall the connector entirely using `--uninstall` to wipe DPAPI state, then reinstall the stable version.

## 3. PASS/BLOCKED Matrix

| Component | Status | Details |
| --- | --- | --- |
| Server Startup (Canary) | PASS | Successfully runs on Postgres. |
| Connector Enrollment (Canary) | PASS | `bootstrap.dpapi` consumed, `device-key.dpapi` generated, API connects successfully. |
| Connector Update/Rollback | PASS | Installer engine recursively copies directories and handles updates. |
| Stale/Offline Denial | BLOCKED | Awaiting user execution/clarification. |
| Uninstall Verification | BLOCKED | Awaiting user execution. |
| Profile Restoration | BLOCKED | Awaiting user execution for 1,189 files manifest. |
| Security / Test-only cleanup | PASS | Clean commit deployed; all temporary token backdoors removed. |

## 4. Remaining External Gates
* **Gate 1:** Execute Stale/Offline denial check.
* **Gate 2:** Execute complete `--uninstall` check on VM.
* **Gate 3:** Execute Exact Profile Restoration check using manifest of 1,189 files on VM.
* **Gate 4:** One Final Regression Suite on VM.
* **Gate 5:** Codex Verification and final sign-off.
