from pathlib import PurePosixPath

import paramiko


ROBOT_IP = "192.168.0.10"
USERNAME = "root"
PASSWORD = "easybot"  # Change if your robot uses another password
PROGRAM_DIRECTORY = "/programs"


def find_urp_files(
    sftp: paramiko.SFTPClient,
    directory: str,
) -> list[str]:
    programs: list[str] = []

    for entry in sftp.listdir_attr(directory):
        path = str(PurePosixPath(directory) / entry.filename)

        # SFTP mode bits beginning with 0o040000 indicate a directory.
        if entry.st_mode & 0o170000 == 0o040000:
            programs.extend(find_urp_files(sftp, path))
        elif entry.filename.lower().endswith(".urp"):
            programs.append(path)

    return programs


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            ROBOT_IP,
            username=USERNAME,
            password=PASSWORD,
            timeout=5,
        )

        with ssh.open_sftp() as sftp:
            programs = find_urp_files(sftp, PROGRAM_DIRECTORY)

        if not programs:
            print("No .urp programs found.")
            return

        print(f"Found {len(programs)} program(s):")
        for program in sorted(programs, key=str.lower):
            print(program)

    except Exception as error:
        print(f"Could not read programs from the robot: {error}")

    finally:
        ssh.close()


if __name__ == "__main__":
    main()