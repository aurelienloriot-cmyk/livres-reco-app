"""Lance l'application en local : python run.py puis http://127.0.0.1:5000"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
