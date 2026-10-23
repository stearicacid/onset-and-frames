cd /home/rin/onset-and-frames/src/onsets-and-frames
export CUDA_VISIBLE_DEVICES=0

taskset -c 0-39 python train.py