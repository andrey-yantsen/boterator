Before first run of docker-compose you should install required dependencies
and compile translation files:

```
docker run -it --rm -v `pwd`:/usr/src/app --entrypoint bash virus/boterator -c 'pip3 install -r requirements.txt'
docker run -it --rm -v `pwd`:/usr/src/app --entrypoint bash virus/boterator -c 'make compile_messages'
```