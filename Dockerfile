# Imagem sem etapa de resolução de dependência, porque não há dependência de runtime a
# resolver (ADR-0001). O resultado é um build que não fala com índice de pacote nenhum.
FROM python:3.14-slim

# Não escrever .pyc e não bufferizar stdout: log de container tem que sair na hora.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Só o necessário para servir. Teste, tooling e docs não vão para a imagem.
COPY src/ /app/src/
COPY data/ /app/data/

# Usuário não-root com home próprio. Rodar como root num container que atende HTTP é
# risco sem contrapartida.
RUN useradd --create-home --uid 10001 obsgov \
    && chown -R obsgov:obsgov /app
USER obsgov

EXPOSE 8000

# A porta não é fixada: a plataforma injeta PORT e o default da CLI lê do ambiente.
# 0.0.0.0 aqui porque dentro do container o bind precisa aceitar o tráfego do proxy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4).status==200 else 1)"

CMD ["sh", "-c", "python -m obsgov.cli serve /app/data --host 0.0.0.0 --port ${PORT:-8000}"]
