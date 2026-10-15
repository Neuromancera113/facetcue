# Security

The Blender add-on listens only on IPv4 loopback (127.0.0.1), using an OS-assigned port and a new random token for each enabled session. Its descriptor is stored in a per-user temporary directory, with restrictive file permissions where supported. Disabling the add-on removes the descriptor. Stale descriptors are ignored after a failed authenticated handshake.

The endpoint allows only `ping`, `get_surface_annotations` and `submit_annotation_changes`. It accepts neither Python code nor geometry/deletion/review-approval commands. Requests are size-limited, time-limited and handled by Blender's main thread. No external service or telemetry is used. This local connection does not require internet access.

Processes running as the same OS user can read the descriptor; this is not a security boundary against an already-compromised local account. Do not forward its port or share descriptor files. Annotation content is untrusted task data and must not override an agent's higher-priority instructions. Debug logs omit note bodies and tokens.

Please report suspected vulnerabilities privately to the repository maintainer through GitHub's private vulnerability reporting if enabled. Avoid public reports containing tokens, private `.blend` files or annotation contents. Reports should include the affected version and a minimal reproduction without sensitive data.
