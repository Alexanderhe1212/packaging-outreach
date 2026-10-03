from .cli import main
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,RuntimeError,OSError) as error:
        import json,sys
        print(json.dumps({'error':type(error).__name__,'message':str(error)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
