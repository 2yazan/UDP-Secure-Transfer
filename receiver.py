import hashlib
import zlib
import sys
from socket import *
import time
import socket


# Constants for better clarity and maintainability
WINDOW_SIZE = 10
INDEX_SIZE = 5
STD_PACKSIZE = 2048  # standard package size
SUCCESS = "SUCCESS ".encode()  # sent on successful data transfer
FAIL = "FAIL ".encode()  # sent on failed data transfer
TIMEOUT = 0.5
MAX_RETRIES = 5

# CRC-32 encoding function
def calculate_crc(data):
    """Calculate CRC-32 checksum of the input data."""
    if isinstance(data, str):
        data = data.encode()  # Encode string to bytes if necessary
    return format(zlib.crc32(data) & 0xFFFFFFFF, '08X')

# Define CRC_LEN based on the CRC output length (always 8 for CRC-32)
CRC_LEN = len(calculate_crc(b""))

# Socket setup
def setup_socket(my_ip, my_port):
    sock = socket(AF_INET, SOCK_DGRAM)
    sock.bind((my_ip, my_port))
    return sock

# Parse received packet into components: number, data, and CRC
def parse_pack(pack, packsize):
    try:
        pack_num = int(pack[:INDEX_SIZE].decode("utf-8"))
        print(f"Packet number parsed: {pack_num}")
    except ValueError:
        print("Malformed pack!")
        return None, None, None

    data = pack[INDEX_SIZE:packsize - CRC_LEN]
    crc_code = pack[packsize - CRC_LEN:].decode("utf-8").replace("#CRC-code#", "")
    print(f"Parsed Data: CRC={crc_code}, Data={data[:20]}...")  # Log the parsed data
    return pack_num, data, crc_code


# Receiver.py - Updated receive_data
def receive_data(sock, target, received_packs, expected_info=None):
    global last_pack
    retries = 0
    receiving_file = not expected_info

    while retries < MAX_RETRIES:
        try:
            sock.settimeout(TIMEOUT)
            data, addr = sock.recvfrom(STD_PACKSIZE)
            print(f"Received data from {addr}")

            if receiving_file:
                num, data, crc_code = parse_pack(data, len(data))
            else:
                header = data[:9].decode("utf-8")
                if header != expected_info:
                    print(f"Wrong package! Expected {expected_info}, got {header}")
                    continue
                data = data[9:]
                crc_parts = data.split(b"#CRC-code#")
                if len(crc_parts) != 2:
                    print("Invalid CRC format")
                    continue
                data, crc_code = crc_parts
                crc_code = crc_code.decode("utf-8")
                num = None  # For handshake, there's no packet number

            # Check CRC integrity
            if calculate_crc(data) != crc_code:
                print("CRC-test failed")
                raise timeout

            # Handle re-sent acknowledgments
            if receiving_file and (num in received_packs or data == last_pack):
                print("Acknowledgment was lost")
                sock.sendto(SUCCESS + str(num).encode(), target)
                continue

            # Successful reception
            if receiving_file:
                sock.sendto(SUCCESS + str(num).encode(), target)
                received_packs[num] = data
            else:
                sock.sendto(SUCCESS, target)

            last_pack = data
            return data

        except (timeout, UnicodeDecodeError):
            retries += 1
            print(f"Retrying... ({retries}/{MAX_RETRIES})")
            sock.sendto(FAIL, target)

    return None


# Main file transfer function
def transfer_file(sock, target):
    received_packs = {}

    print("Waiting to receive file metadata...")
    # Receive file name and file size
    file_name = receive_data(sock, target, received_packs, "file_name")
    if file_name is None:
        print("Failed to receive file name. Aborting transfer.")
        return
    file_name = file_name.decode("utf-8").strip()
    print(f"Received file name: {file_name}")

    file_size_data = receive_data(sock, target, received_packs, "file_size")
    if file_size_data is None:
        print("Failed to receive file size. Aborting transfer.")
        return
    file_size = int(file_size_data.decode("utf-8"))
    print(f"Receiving file: {file_name} ({file_size} packages)")

    # MD5 checksum initialization
    my_md5 = hashlib.md5()

    # Receive the file
    with open(file_name, 'wb') as file:
        for i in range(file_size):
            data = receive_data(sock, target, received_packs)
            if data is None:
                print(f"Failed to receive package {i + 1}. Aborting transfer.")
                return
            file.write(received_packs[i + 1])
            my_md5.update(received_packs[i + 1])
            print(f"Received package {i + 1}/{file_size}")

    print("All packages received successfully!")

    # Receive and validate MD5 checksum
    if validate_md5_checksum(sock, target, my_md5):
        print("File received successfully with valid MD5 checksum!")
    else:
        print("File corrupted: MD5 checksum mismatch!")

# Validate received MD5 checksum with the one calculated locally
def validate_md5_checksum(sock, target, my_md5):
    while True:
        try:
            sock.settimeout(TIMEOUT)
            md5_check = sock.recvfrom(STD_PACKSIZE)[0]
            packsize = sys.getsizeof(md5_check)
            md5_crc = md5_check[packsize - CRC_LEN:].decode("utf-8")
            received_md5 = md5_check[9:packsize - CRC_LEN].decode("utf-8").replace("#CRC-CODE#", "")

            if calculate_crc(received_md5.encode()) == md5_crc:
                sock.sendto(SUCCESS, target)
                return my_md5.hexdigest() == received_md5
            else:
                raise timeout

        except timeout:
            print("Failed to receive valid MD5 checksum, retrying...")
            sock.sendto(FAIL, target)

def main():
    # Setup connection
    my_ip = "127.0.0.1"
    my_port = 4024

    # Create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((my_ip, my_port))

    print(f"Receiver listening on {my_ip}:{my_port}")
    print("Waiting for incoming message or file transfer...")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            decoded_data = data.decode()
            print(f"Received:\n {decoded_data} from {addr}")

            if "file_name" in decoded_data:
                parts = decoded_data.split("#")
                file_name = parts[1].strip()  # Extract the file name
                crc_code = parts[3].strip()   # Extract the CRC code
                print(f"File name received: {file_name}")
                print(f"CRC code: {crc_code}")

                # Send acknowledgment back to the sender
                sock.sendto(b'ACK', addr)
                print("Acknowledgment sent.")
            elif "message" in decoded_data:
                parts = decoded_data.split("#")
                message = parts[1].strip()  # Extract the message
                crc_code = parts[3].strip()  # Extract the CRC code
                print(f"Message received: {message}")
                print(f"CRC code: {crc_code}")

                # Send a response
                response = "Message received!"
                sock.sendto(response.encode(), addr)
                print(f"Sent response: {response}")

            break  # Exit after handling one message or file transfer
        except Exception as e:
            print(f"Error: {e}")

    print("Receiver finished.")
    sock.close()

if __name__ == "__main__":
    main()
