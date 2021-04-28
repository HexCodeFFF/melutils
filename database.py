import sqlite3

# just making the connection and cursor objects available for any file that imports it should be good enough
connection = sqlite3.connect('database.sqlite')
cursor = connection.cursor()
