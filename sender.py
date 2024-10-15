import os
import zlib
from socket import *
import socket

# Constants for better clarity and maintainability
WINDOW_SIZE = 10
PACK_SIZE = 1024
SUCCESS = "SUCCESS ".encode()
TIMEOUT = 0.5
MAX_RETRIES = 5

# CRC-32 encoding function
def calculate_crc(data):
    """Calculate CRC-32 checksum of the input data."""
    if isinstance(data, str):
        data = data.encode()  # Encode string to bytes if necessary
    return format(zlib.crc32(data) & 0xFFFFFFFF, '08X')


# Socket setup
def setup_socket(my_ip, my_port):
    sock = socket(AF_INET, SOCK_DGRAM)
    sock.bind((my_ip, my_port))
    return sock

# Send a single data packet
def send_data(sock, data, target, encoded=False, is_retry=False, include_md5=False, extra_info=""):
    if not is_retry:
        if not encoded:
            crc_code = calculate_crc(data.encode())
            data = f"{data}#CRC-code#{crc_code}"
            if extra_info:
                data = extra_info + data
            data = data.encode()
        else:
            crc_code = calculate_crc(data)
            data += f"#CRC-code#{crc_code}".encode()

    if include_md5:
        print("MD5:", data)

    retries = 0
    while retries < MAX_RETRIES:
        try:
            print(f"Sending data to {target}...")
            sock.sendto(data, target)
            print(f"Data sent: {data[:20]}...") # Print first 20 bytes of data
            print("Waiting for acknowledgment...")
            sock.settimeout(TIMEOUT)
            conf, addr = sock.recvfrom(PACK_SIZE)
            print(f"Received response from {addr}: {conf}")
            if conf == SUCCESS:
                print("Success acknowledgment received.")
                return True
            else:
                print(f"Unexpected response: {conf}")
                raise timeout
        except timeout:
            retries += 1
            print(f"Timeout occurred. Retrying... ({retries}/{MAX_RETRIES})")
        except ConnectionResetError:
            retries += 1
            print(f"Connection reset. Retrying... ({retries}/{MAX_RETRIES})")
        except Exception as e:
            retries += 1
            print(f"Unexpected error: {e}. Retrying... ({retries}/{MAX_RETRIES})")

    print("Max retries reached. Unable to send data.")
    return False

# Send an array of data (windowed transmission)
def send_data_array(sock, data_array, target):
    acks_received = set()

    while len(acks_received) < len(data_array):  # Wait for all acknowledgments
        for packet_id, data in data_array.items():
            if packet_id not in acks_received:  # Resend unacknowledged packets
                print(f"Sending packet {packet_id}")
                sock.sendto(data, target)

        # Process acknowledgments
        try:
            sock.settimeout(TIMEOUT)
            ack = sock.recvfrom(PACK_SIZE)[0].decode('utf-8').split()
            if ack[0] == "SUCCESS":
                packet_ack = int(ack[1])
                print(f"Packet {packet_ack} acknowledged")
                acks_received.add(packet_ack)
        except (timeout, UnicodeDecodeError, IndexError):
            print("Error processing acknowledgment or timeout, resending unacknowledged packets.")

# Form a packet with CRC and sequence number
def form_packet(data, packet_id):
    crc_code = calculate_crc(data)
    packet_id_str = f"{packet_id:05}"  # Ensure 5-digit packet ID
    packet = f"{packet_id_str}".encode() + data + crc_code.encode()
    print(f"Formed Packet: ID={packet_id}, CRC={crc_code}, Data={data[:20]}...")  # Log the packet
    return packet

# Function to transfer the file
def transfer_file(sock, target, file_name):
    print(f"Starting file transfer process for {file_name}...")

    # Calculate dynamic CRC
    crc_code = calculate_crc(file_name)
    message = f"file_name#{file_name}#CRC-code#{crc_code}"

    max_retries = 5
    timeout = 2

    for attempt in range(max_retries):
        print(f"Sending data to {target}...")
        sock.sendto(message.encode(), target)
        print(f"Data sent: {message.encode()}...")

        # Set timeout for the response
        sock.settimeout(timeout)

        try:
            response, addr = sock.recvfrom(1024)  # Buffer size can be adjusted
            print(f"Received response from {addr}: {response.decode()}")
            if response == b'ACK':
                print("Acknowledgment received. File transfer successful.")
                break  # Exit the loop on successful acknowledgment
            else:
                print(f"Unexpected response: {response}")

        except socket.timeout:
            print(f"Timeout occurred. Retrying... ({attempt + 1}/{max_retries})")

    else:
        print("Max retries reached. Unable to send data.")
        print("Failed to send file name. Aborting transfer.")


# Send the final MD5 checksum for file validation
def send_md5_checksum(sock, target, md5):
    while True:
        md5_hash = md5.hexdigest()
        crc_code = calculate_crc(md5_hash.encode())
        checksum_data = f"file_hash{md5_hash}#CRC-CODE#{crc_code}".encode()
        sock.sendto(checksum_data, target)
        try:
            sock.settimeout(TIMEOUT)
            conf = sock.recvfrom(PACK_SIZE)
            if conf[0] == SUCCESS:
                print("MD5 checksum sent successfully.")
                break
        except timeout:
            print("Resending MD5 checksum...")


def main():
    # Setup connection
    my_ip = "127.0.0.1"
    my_port = 4023
    target_ip = "127.0.0.1"
    target_port = 4024

    # Create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((my_ip, my_port))
    print(f"Sender set up on {my_ip}:{my_port}")
    print(f"Target set to {target_ip}:{target_port}")

    choice = input("Enter 'file' to send a file or 'message' to send a message: ")

    if choice == "message":
        message = input("Enter the message to send: ")
        crc_code = calculate_crc(message)
        data = f"message#{message}  #  CRC-code#{crc_code}"
        print(f"Sending message with CRC:\n {data}")
        sock.sendto(data.encode(), (target_ip, target_port))

        print("Waiting for response...")
        sock.settimeout(5)
        try:
            data, addr = sock.recvfrom(1024)
            print(f"Received response from {addr}: {data.decode()}")
        except socket.timeout:
            print("No response received. Receiver might not be running or reachable.")

    elif choice == "file":
        file_name = input("Enter the file name to send: ")
        if os.path.exists(file_name):
            transfer_file(sock, (target_ip, target_port), file_name)
        else:
            print("File not found!")

    print("Closing socket...")
    sock.close()
    print("Sender finished.")

if __name__ == "__main__":
    main()

