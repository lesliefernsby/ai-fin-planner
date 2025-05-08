# AI-Fin-Planner

Monorepo for financial-planning microservices.  
- **services/finplanbot** – Telegram bot + OpenAI OCR  
- …future services…

## Adding a new service

1. Create `services/<your-service>`  
2. Include `Dockerfile`, `requirements.txt` (or equivalent), code, tests  
3. Update `infra/docker-compose.yml` and `.github/workflows/ci-cd.yml`
