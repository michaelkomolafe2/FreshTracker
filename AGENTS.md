{\rtf1\ansi\ansicpg1252\cocoartf2865
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww30040\viewh16020\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # Project: FreshTracker\
You are an expert backend engineer and UI developer helping me build a food waste tracking app.\
\
## Stack\
* Backend: Python 3.10, Flask, PostgreSQL (via SQLAlchemy)\
* Frontend: React, Tailwind CSS\
* ML: scikit-learn\
\
## Engineering Conventions & Constraints\
* **Backend:** All API endpoints must return standard JSON. Always use RESTful naming conventions. \
* **Database:** Never drop tables in production; use migrations if schema changes.\
* **Frontend:** Do NOT write custom CSS files. Use Tailwind utility classes exclusively. Keep components strictly functional.\
* **Testing:** All Python logic must have accompanying `pytest` assertions.\
\
## Definition of Done\
Code is only "done" when tests pass, edge cases (like missing data) are handled gracefully, and the application can run successfully via `docker-compose up`.}