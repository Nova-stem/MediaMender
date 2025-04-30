# src/media_processor.py

import time
import random

class MediaProcessor:
    def __init__(self, config):
        self.config = config

    def process_file(self, filepath):
        # Placeholder for actual processing logic
        # Replace this with your real stitching, renaming, encoding steps
        try:
            print(f"Processing {filepath}...")
            time.sleep(random.uniform(0.5, 1.2))  # Simulate work
            if random.random() < 0.1:  # Simulate occasional failure
                raise RuntimeError("Fake processing error.")
            return True
        except Exception as e:
            print(f"Error processing {filepath}: {e}")
            return False

def simulate_processing(filepath):
    # Used by the worker thread
    try:
        print(f"Simulating processing: {filepath}")
        time.sleep(random.uniform(0.4, 1.0))  # Simulated delay
        if random.random() < 0.15:
            raise Exception("Simulated error")
        return True
    except Exception as e:
        print(f"[Sim Error] {filepath}: {e}")
        return False
