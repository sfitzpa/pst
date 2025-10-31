up:        ## start stack
\tdocker compose up -d
down:      ## stop stack
\tdocker compose down
logs-api:  ## tail API logs
\tdocker logs -f pst-api
psql:      ## open psql in DB container
\tdocker exec -it pst-postgres psql -U pst -d pst
seed:      ## seed minimal data
\tbash scripts/seed_minimal.sh
weights:   ## recompute weights now
\tdocker exec -it pst-postgres psql -U pst -d pst -c "UPDATE trajectory SET weight = 1 - exp(-0.15 * freq);"
backup:
\tbash scripts/backup.sh
