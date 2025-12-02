
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# MySQL connection URL
# Replace password with your own
DATABASE_URL = "mysql+pymysql://root:root@localhost:3306/mysql_db"

# Create a connection to MySQL
engine = create_engine(DATABASE_URL)

# This creates a session to talk to the database
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

# Base class for creating tables
Base = declarative_base()
