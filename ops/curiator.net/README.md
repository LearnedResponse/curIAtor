# curiator.net operations

The public galleries run on a private workstation and reach the GCP Caddy edge through one rathole
client. A rathole control process can remain alive after individual data-channel handshakes stop
recovering, so `Restart=always` on the client service is not sufficient by itself.

`curiator-tunnel-healthcheck` checks the public bootstrap endpoint for every gallery. On failure it:

1. verifies each gallery directly on its local port;
2. repeats the public check after five seconds;
3. restarts `rathole-sietch.service` only when local backends are healthy and the edge still fails;
4. verifies the public routes again after restart.

The timer runs this check every three minutes. Install the script in `~/.local/bin/`, copy the two
units into `~/.config/systemd/user/`, then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rathole-sietch-healthcheck.timer
```

Override `CURIATOR_HEALTH_PUBLIC_BASE`, `CURIATOR_HEALTH_TARGETS`, or
`CURIATOR_RATHOLE_SERVICE` in the service environment for another deployment. No tunnel tokens or
private keys belong in these files.
