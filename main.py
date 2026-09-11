import sys

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "api"
    if cmd == "ingest":
        from src.rag.ingest import ingest_data
        sys.exit(0 if ingest_data(force=True) else 1)
    elif cmd == "api":
        import uvicorn
        uvicorn.run("api.server:app", host="0.0.0.0", port=8001, reload=True)
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
