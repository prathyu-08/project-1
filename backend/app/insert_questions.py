

from .db import SessionLocal, engine, Base
from .models import Question
from sqlalchemy.orm import Session


QUESTIONS = [
    {
        "text": "What is the output of print(2**3)?",
        "choices": ["6", "8", "9"],
        "answer_index": 1,
        "difficulty": "easy",
    },
    {
        "text": "Which keyword is used to create a class in Python?",
        "choices": ["function", "class", "object"],
        "answer_index": 1,
        "difficulty": "easy",
    },
    {
        "text": "What is the time complexity of binary search?",
        "choices": ["O(n)", "O(log n)", "O(n log n)"],
        "answer_index": 1,
        "difficulty": "medium",
    },
    {
        "text": "Which data structure uses FIFO?",
        "choices": ["Stack", "Queue", "Tree"],
        "answer_index": 1,
        "difficulty": "easy",
    },
    {
        "text": "Which operator is used to compare two values?",
        "choices": ["=", "==", "==="],
        "answer_index": 1,
        "difficulty": "easy",
    },
    {
        "text": "What does the len() function return?",
        "choices": ["Length", "Sum", "Type"],
        "answer_index": 0,
        "difficulty": "easy",
    },
    {
        "text": "What is a correct file extension for Python files?",
        "choices": [".py", ".pt", ".pyt"],
        "answer_index": 0,
        "difficulty": "easy",
    },
    {
        "text": "Which sorting algorithm has the best average performance?",
        "choices": ["Bubble Sort", "Merge Sort", "Selection Sort"],
        "answer_index": 1,
        "difficulty": "medium",
    },
    {
        "text": "Which structure is used for key-value pairs?",
        "choices": ["List", "Dictionary", "Tuple"],
        "answer_index": 1,
        "difficulty": "easy",
    },
    {
        "text": "Which keyword is used to start a loop in Python?",
        "choices": ["for", "repeat", "loop"],
        "answer_index": 0,
        "difficulty": "easy",
    },
]

def insert_questions():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    count = 0
    for q in QUESTIONS:
        exists = db.query(Question).filter(Question.text == q["text"]).first()
        if exists:
            continue
        new_q = Question(
            text=q["text"],
            choices=q["choices"],
            answer_index=q["answer_index"],
            difficulty=q["difficulty"]
        )
        db.add(new_q)
        count += 1

    db.commit()
    db.close()
    print(f"Inserted {count} new questions (or skipped existing).")

if __name__ == "__main__":
    insert_questions()
