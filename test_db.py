import psycopg2
from sys import argv

if __name__ == '__main__':
    psycopg2.connect("user='" + argv[2] + "' host='" + argv[1] + "' password='" + argv[3] + "'")