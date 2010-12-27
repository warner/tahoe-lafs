start:
	twistd web --path . -p 8444
	@echo http://localhost:8444/index.html
stop:
	kill `cat twistd.pid`

output.js: build.py kernel.js setup.js user.js jquery-1.4.3.min.js
	./build.py user.py >output.js

