# Security Policy & Responsible Use

## 1. Physical Access Control & Door Unlock Safety
This repository documents the `LockControl` protocol opcode and provides reference door-unlock scripts (`examples/door-unlock.sh`):
- **Safety Warning:** Door unlock scripts actuate physical relays and magnetic door strikes.
- **Fail-Safe Requirement:** Never execute unlock automation on active physical security barriers without an independent physical manual key override.
- Test unlock scripts strictly on isolated lab benches.

## 2. Research & Clean-Room Interoperability
This repository is an independent reverse-engineered specification developed strictly for Linux interoperability without proprietary vendor SDKs.

## 3. Reporting Security Issues
To report a vulnerability or sensitive finding, please contact the maintainer directly at `vibhav.aggarwal2@gmail.com` or via GitHub Security Advisories.
