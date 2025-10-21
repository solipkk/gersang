import gdown
import imax

def google_drive_download(file_id, dest_path):

#	imax.print('file_id: ', file_id)
#	imax.print('dest_path: ', dest_path)

	if dest_path == "":
		imax.print('dest_path does not exist.')
	else:
		gdown.download(id=file_id, output=dest_path, quiet=True)
	return True
