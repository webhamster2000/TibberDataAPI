# Note
This code is not related in any way to the company Tibber.
It just implements the authorization and reading devices part of the public API defined in https://data-api.tibber.com/docs

This allows to read the charging data for connect electric vehicles. It is tested for Cupra, but should work as well for all other cars which can be connected to Tibber.

It bypasses the latest restrictions e.g. from VW by using the official, registered and legal API.

See https://tibber.com/de/magazine/power-hacks/volkswagen-api-zugriff

# Setup
Go to https://data-api.tibber.com/clients/manage/ and create an OAuth2 client.
Set the redirect URI to http://localhost:17235/callback.
Run the script

# Pass credentials directly
python tibber_devices.py --client-id YOUR_ID --client-secret YOUR_SECRET

# Or via environment variables

export TIBBER_CLIENT_ID=YOUR_ID

export TIBBER_CLIENT_SECRET=YOUR_SECRET

python tibber_devices.py

# What it does
## First run:

opens your browser for Tibber login, catches the OAuth callback automatically on port 17235, exchanges the code for tokens, and saves them to ~/.tibber_tokens.json (mode 600).

## Subsequent runs:
uses the stored refresh token silently — no browser needed.

Lists all homes → all devices → full device detail JSON for each.

Useful flags

# Force re-authentication (e.g. different account or expired refresh token)
python tibber_devices.py --client-id X --client-secret Y --reauth

The only stdlib dependency is Python 3.10+ (uses dict | list type hint — easily removable if you're on 3.9).
