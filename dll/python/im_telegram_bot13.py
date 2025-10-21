import imax
import requests
import os.path

# 메세지 전송 함수
def telegram_sendmessage(token, chat_id, text):
	url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}"
	data = {'chat_id': chat_id, 'text': text}
	response = requests.post(url, data=data)
	json = response.json()
#	print(f"메세지 전송 결과 \n{json}")
#	{'ok': True, 'result': {...}}
	if json['ok'] is False:
		imax.print("메세지 전송을 실패하였습니다.")
		return -1
	return 1

# 스샷 전송 함수
def telegram_sendphoto(token, chat_id, image_path, image_caption=""):
	if not os.path.isfile(image_path):
		imax.print('file does not exist: ', image_path)
		return -1
	data = {"chat_id": chat_id, "caption": image_caption}
	url = f"https://api.telegram.org/bot{token}/sendPhoto?chat_id={chat_id}"
	with open(image_path, "rb") as image_file:
		response = requests.post(url, data=data, files={"photo": image_file})
	json = response.json()
#	print(f"스샷 전송 결과 \n{json}")
	if json['ok'] is False:
		imax.print("스샷 전송을 실패하였습니다.")
		return -1
	return 1

#import os
#print("Current working directory: {0}".format(os.getcwd()))
