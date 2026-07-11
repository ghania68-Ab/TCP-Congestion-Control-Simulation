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
| Loss Threshold (BDP + Queue) | 26 packets |

## What We Did

1. Designed a discrete-event simulation modeling a sender, a bottleneck router, and a receiver.
2. Implemented TCP Tahoe congestion control (Slow Start, Congestion Avoidance, Fast Retransmit, timeout recovery).
3. Implemented TCP Reno congestion control (same as Tahoe plus Fast Recovery with window inflation).
4. Used a probabilistic loss model triggered when cwnd exceeds BDP + router queue capacity (26 packets), simulating queue overflow at the bottleneck router.
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

**Key difference**: Reno's Fast Recovery avoids the costly cwnd = 1 reset on single-packet losses detected via triple duplicate ACKs, maintaining a higher average sending rate.

## Results Summary

| Metric | TCP Tahoe | TCP Reno | Difference |
|--------|-----------|----------|------------|
| Average cwnd | 40.06 pkts | 40.78 pkts | +1.8% |
| Max cwnd | 64.2 pkts | 55.9 pkts | -12.9% |
| cwnd Std Dev | 5.35 pkts | 4.32 pkts | -19.3% |
| Average RTT | 318.9 ms | 326.8 ms | +2.5% |
| Overall Drop Rate | 7.94% | 8.53% | +7.4% |
| Average Throughput | 1,215.6 kbps | 1,356.0 kbps | +11.5% |
| Max Throughput | 1,337.6 kbps | 1,368.5 kbps | +2.3% |
| Packets Dropped | 2,383 / 30,000 | 2,559 / 30,000 | — |

## Conclusion

TCP Reno achieves approximately **11.5%** higher throughput than TCP Tahoe (1,356.0 kbps vs 1,215.6 kbps) due to its **Fast Recovery** mechanism, which avoids restarting from **cwnd = 1** after triple duplicate ACKs. This results in higher bottleneck utilization (**90.4% vs 81.0%**) and more stable **cwnd**, with only a slightly higher drop rate (**8.53% vs 7.94%**). These findings are consistent with networking literature showing that **Fast Recovery** improves throughput under packet-loss conditions.

## How to Run

```bash
pip install matplotlib numpy
cd code/
python tcp_simulation.py
```

Output graphs and statistics are saved in the `output/` directory. Works on Windows, macOS, and Linux.

## Folder Structure

```
CN-TahoeReno/
├── code/
│   ├── tcp_simulation.py        # Main simulation script (run this)
│   └── README.md                # Project documentation
├── output/
│   ├── cwnd_comparison.png      # Congestion window graph (single run)
│   ├── rtt_comparison.png       # Round-trip time graph (single run)
│   ├── drop_rate_comparison.png # Packet drop rate graph (5-run average)
│   ├── throughput_comparison.png# Throughput graph (5-run average)
│   ├── summary_dashboard.png    # All 4 metrics combined dashboard
│   ├── simulation_stats.json    # Full results in JSON format
│   └── csv/
│       ├── cwnd_data.csv        # Congestion window per ACK event
│       ├── rtt_data.csv         # RTT per ACK event
│       ├── throughput_data.csv  # Throughput per ACK event (5-run avg)
│       ├── drop_rate_data.csv   # Drop rate per ACK event (5-run avg)
│       └── summary_results.csv  # Final stats table (Tahoe vs Reno)
└── report.pdf                   # Technical report (PDF)
```

## Author

**Ghania Jawed**

This is my 6th semester project for the Computer Networks course.