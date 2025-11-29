# create_db.py
from db import Base, engine  # Import from your db.py
import models 

print("Creating DB and tables...")
Base.metadata.create_all(bind=engine)
db = SessionLocal()

# create admin user (email: admin@nmk.com / password: adminpass)
admin_email = "admin@nmk.com"
if not db.query(models.User).filter(models.User.email == admin_email).first():
    hashed = auth.get_password_hash("adminpass")
    admin = models.User(email=admin_email, name="Admin", hashed_password=hashed, is_admin=True)
    db.add(admin)
    db.commit()
    print("Created admin user:", admin_email, "password: adminpass")
else:
    print("Admin exists")

# create some sample questions (3 easy, 3 medium, 3 hard) if none exist
if db.query(models.Question).count() == 0:
    samples = [
        ("What is 2 + 2?", ["1","2","3","4"], 3, "easy"),
        ("What is the capital of France?", ["Berlin","Paris","Madrid","Rome"], 1, "easy"),
        ("Which of these is a Python data type?", ["map","list","array","table"], 1, "easy"),
        ("What does HTTP stand for?", ["HyperText Transfer Protocol", "HighText Transfer", "Hyper Transfer Protocol", "Home Transfer"], 0, "medium"),
        ("Which SQL statement is used to create a table?", ["CREATE", "INSERT", "UPDATE", "DROP"], 0, "medium"),
        ("What is Big-O of binary search?", ["O(n)","O(log n)","O(n log n)","O(1)"], 1, "medium"),
        ("Which sorting algorithm is in-place and unstable?", ["Merge Sort","Quick Sort","Heap Sort","Bubble Sort"], 1, "hard"),
        ("What is the output of this python: sorted({3:1,2:2}.items(), key=lambda x: x[1]) ?", ["[(3,1),(2,2)]","[(2,2),(3,1)]","error","none"], 0, "hard"),
        ("In distributed systems, CAP theorem states:", ["Consistency, Availability, Partition tolerance (choose two)", "Capacity, Availability, Persistence","Consistency, Access, Partition","Connect, Apply, Persist"], 0, "hard"),
    ]
    for text, choices, ans, diff in samples:
        q = models.Question(text=text, choices=choices, answer_index=ans, difficulty=diff)
        db.add(q)
    db.commit()
    print("Added sample questions")
else:
    print("Questions already present")

db.close()
print("Done.")
