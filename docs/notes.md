# harden fpga

tt/tt_fpga.py harden

# load the fpga

tt/tt_fpga.py configure --port /dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_6f890b97e48ced01-if00 --upload --set-default --clockrate 50000000

# setup the pulse

python scripts/run_freq.py 1000 --offset 0 --enc-step 1
