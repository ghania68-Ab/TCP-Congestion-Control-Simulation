# TCP Tahoe vs Reno: Congestion Control Simulation

## Project Description

This project simulates and compares two fundamental TCP congestion control algorithms — **TCP Tahoe** and **TCP Reno** — over a simple wired network with a bottleneck link. A discrete-event simulation is implemented in Python, where each time step represents an ACK event. The simulation captures congestion window behavior, RTT variations, packet drop rates, and throughput for both algorithms under identical network conditions. Results are averaged over 5 independent runs of 6,000 ACK events each, and comparison graphs are generated automatically.

## Network Topology

```
Sender ----[10 Mbps, 5 ms]----> Router ----[1.5 Mbps, 20 ms]----> Receiver
                                                    |
                                              Bottleneck Link
```

| Parameter | Value |
|-----------|-------|
| Sender → Router Bandwidth | 10 Mbps |
| Router → Receiver Bandwidth | 1.5 Mbps (bottleneck) |
| Sender → Router Delay | 5 ms |
| Router → Receiver Delay | 20 ms |
| Base RTT | 50 ms |
| Packet Size | 1500 bytes |
| Router Queue Capacity | 20 packets |
| Bandwidth-Delay Product (BDP) | 6 packets |

## What We Did

1. Designed a discrete-event simulation modeling a sender, a bottleneck router, and a receiver.
2. Implemented TCP Tahoe congestion control (Slow Start, Congestion Avoidance, Fast Retransmit, timeout recovery).
3. Implemented TCP Reno congestion control (same as Tahoe plus Fast Recovery with window inflation).
4. Used a probabilistic loss model triggered when cwnd exceeds BDP, simulating queue overflow.
5. Applied Jacobson/Karels RTT estimation for dynamic timeout calculation.
6. Ran each algorithm 5 times with different random seeds and averaged the results.
7. Generated publication-quality comparison graphs (cwnd, RTT, drop rate, throughput, dashboard).

## Algorithms Used

### TCP Tahoe
- **Slow Start**: cwnd doubles every RTT (exponential growth) until ssthresh is reached.
- **Congestion Avoidance**: cwnd grows linearly (+1/cwnd per ACK) after ssthresh.
- **On 3 Duplicate ACKs**: Sets ssthresh = cwnd/2, resets cwnd = 1, re-enters Slow Start.
- **On Timeout**: Sets ssthresh = cwnd/2, resets cwnd = 1, re-enters Slow Start.

### TCP Reno
- **Slow Start & Congestion Avoidance**: Identical to Tahoe.
- **On 3 Duplicate ACKs**: Sets ssthresh = cwnd/2, sets cwnd = ssthresh + 3, enters **Fast Recovery** — cwnd inflates by +1 per additional dup ACK, and exits to Congestion Avoidance on a new ACK.
- **On Timeout**: Falls back to Tahoe behavior (cwnd = 1, Slow Start).

**Key difference**: Reno's Fast Recovery avoids the costly cwnd = 1 reset on single-packet losses, maintaining a higher average sending rate.

## Results Summary

| Metric | TCP Tahoe | TCP Reno | Difference |
|--------|-----------|----------|------------|
| Average cwnd | 50.68 pkts | 55.32 pkts | +9.2% |
| Average RTT | 380.1 ms | 397.8 ms | +4.7% |
| Overall Drop Rate | 6.99% | 8.15% | +16.6% |
| **Average Throughput** | **1,406.0 kbps** | **1,539.9 kbps** | **+9.5%** |
| Packets Dropped | 2,096 / 30,000 | 2,444 / 30,000 | — |

## Conclusion

TCP Reno outperforms TCP Tahoe by approximately **9.5% in average throughput** (1,539.9 kbps vs 1,406.0 kbps). This improvement is directly attributable to Reno's Fast Recovery mechanism, which avoids resetting the congestion window to 1 after single-packet losses detected via triple duplicate ACKs. While Reno shows a slightly higher drop rate (8.15% vs 6.99%) due to its more aggressive window probing, it compensates by spending far less time in the low-throughput Slow Start recovery phase. For wired networks where single-packet losses are the dominant congestion signal, TCP Reno is the superior choice.

## How to Run

```bash
pip install matplotlib numpy
cd code/
python tcp_simulation.py
```

Output graphs and statistics are saved in the `output/` directory. Works on Windows, macOS, and Linux.

## Team Members

| Name |
|------|
| Ghania Jawed |
