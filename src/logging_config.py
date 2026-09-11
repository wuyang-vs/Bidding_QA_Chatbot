import logging, sys
_configured = False
def setup_logging(level=logging.INFO):
    global _configured
    if _configured: return
    logging.basicConfig(level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout)
    for n in ("httpx","openai","urllib3","sentence_transformers","jieba"):
        logging.getLogger(n).setLevel(logging.WARNING)
    _configured = True
