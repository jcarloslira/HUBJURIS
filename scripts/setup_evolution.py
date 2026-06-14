"""Script para configurar a Evolution API: criar instância e webhook."""

import sys
import time

import httpx


def main() -> None:
    """Configura a Evolution API com instância e webhook."""
    if len(sys.argv) < 3:
        print("Uso: python scripts/setup_evolution.py <EVOLUTION_URL> <API_KEY> [WEBHOOK_URL]")
        print()
        print("Exemplo:")
        print("  python scripts/setup_evolution.py http://localhost:8080 sua-api-key https://seudominio.com")
        sys.exit(1)

    evolution_url = sys.argv[1].rstrip("/")
    api_key = sys.argv[2]
    webhook_base = sys.argv[3].rstrip("/") if len(sys.argv) > 3 else None
    instance_name = "lorena"
    headers = {"apikey": api_key}

    print(f"\n{'='*50}")
    print("  SETUP EVOLUTION API — Lorena SDR")
    print(f"{'='*50}\n")
    print(f"URL Evolution: {evolution_url}")
    print(f"Instância:     {instance_name}")
    if webhook_base:
        print(f"Webhook:       {webhook_base}/api/webhook/evolution")
    print()

    # 1. Criar instância
    print("[1/3] Criando instância...")
    create_payload = {
        "instanceName": instance_name,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
    }

    try:
        resp = httpx.post(
            f"{evolution_url}/instance/create",
            json=create_payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            print(f"   Instância '{instance_name}' criada!")
            if "qrcode" in data:
                qr = data.get("qrcode", {})
                if isinstance(qr, dict) and qr.get("base64"):
                    print("   QR Code gerado (base64 disponível na resposta)")
                elif isinstance(qr, str):
                    print(f"   QR Code: {qr[:100]}...")
        elif resp.status_code == 403:
            print("   ERRO: API Key inválida. Verifique a variável EVOLUTION_API_KEY.")
            sys.exit(1)
        elif resp.status_code == 409:
            print(f"   Instância '{instance_name}' já existe — OK!")
        else:
            print(f"   Resposta: {resp.status_code} — {resp.text[:200]}")
    except httpx.ConnectError:
        print(f"   ERRO: Não consegui conectar em {evolution_url}")
        print("   Verifique se a Evolution API está rodando.")
        sys.exit(1)

    # 2. Configurar webhook
    if webhook_base:
        print("\n[2/3] Configurando webhook...")
        webhook_url = f"{webhook_base}/api/webhook/evolution"
        webhook_payload = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhookByEvents": False,
                "events": ["MESSAGES_UPSERT"],
            },
        }

        resp = httpx.put(
            f"{evolution_url}/webhook/set/{instance_name}",
            json=webhook_payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"   Webhook configurado: {webhook_url}")
        else:
            print(f"   Aviso: {resp.status_code} — {resp.text[:200]}")
            print(f"   Configure manualmente: {webhook_url}")
    else:
        print("\n[2/3] Webhook — pulando (sem URL fornecida)")
        print("   Configure depois com a URL do seu servidor.")

    # 3. Gerar QR Code para conectar o WhatsApp
    print("\n[3/3] Gerando QR Code para conectar o WhatsApp...")
    time.sleep(2)

    resp = httpx.get(
        f"{evolution_url}/instance/connect/{instance_name}",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 200:
        data = resp.json()
        base64_qr = data.get("base64")
        code = data.get("code")

        if code:
            print(f"\n   QR Code (texto): {code[:80]}...")
        if base64_qr:
            print(f"\n   QR Code (base64): {base64_qr[:80]}...")

        print(f"\n   Abra no navegador para escanear:")
        print(f"   {evolution_url}/instance/connect/{instance_name}")
        print(f"\n   Ou acesse o manager:")
        print(f"   {evolution_url}/manager")
    else:
        print(f"   Status: {resp.status_code}")
        print(f"   Acesse manualmente: {evolution_url}/manager")

    print(f"\n{'='*50}")
    print("  PRÓXIMOS PASSOS")
    print(f"{'='*50}")
    print(f"""
1. Abra {evolution_url}/manager no navegador
2. Faça login com a API Key: {api_key[:8]}...
3. Escaneie o QR Code com o WhatsApp do escritório
4. Teste enviando "Oi" para o número conectado
5. A Lorena vai responder automaticamente!
""")


if __name__ == "__main__":
    main()
