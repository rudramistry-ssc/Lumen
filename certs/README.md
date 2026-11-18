# Extra root certificates (optional)

Some networks inspect HTTPS traffic with their own root certificate (for example
`GOC-GDC-ROOT-A`). Docker builds and the one-time model download then fail with
`CERTIFICATE_VERIFY_FAILED` / `self-signed certificate in certificate chain`.

Put the PEM-encoded root certificate(s) here as `*.crt`. The app image trusts
them automatically; certificate verification is never disabled. `start.ps1`
exports `GOC-GDC-ROOT-A` from the Windows certificate store into this folder for
you when it is present. Only public root certificates belong here, never keys.
