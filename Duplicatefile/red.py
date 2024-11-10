import redis
import json

# Connect to Redis
r = redis.Redis(host="localhost", port=6379)
# Get all keys
keys = r.keys('*')
# Print each key and its corresponding value
for key in keys:
    # Attempt to decode the value as JSON for better readability
    try:
        value = r.hgetall(key)  # Use hgetall for hash-type keys
        if value:
            # Decode bytes to strings for readability
            decoded_value = {k.decode(): v.decode() for k, v in value.items()}
            print(f"Hash Key: {key.decode()} - Value: {json.dumps(decoded_value, indent=2)}")
        else:
            # For non-hash keys, retrieve value directly
            value = r.get(key).decode()
            print(f"Key: {key.decode()} - Value: {value}")
    except Exception as e:
        print(f"Key: {key.decode()} - Error reading value: {e}")