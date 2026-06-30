function haversineDistanceOld(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const deltaPhi = (lat2 - lat1) * Math.PI / 180;
  const deltaLambda = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(deltaPhi / 2) * Math.sin(deltaPhi / 2) +
            Math.cos(phi1) * Math.cos(phi2) *
            Math.sin(deltaLambda / 2) * Math.sin(deltaLambda / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function haversineDistanceNew(lat1, lon1, lat2, lon2) {
  const TO_RAD = 0.017453292519943295; // Math.PI / 180
  const TO_RAD_HALF = 0.008726646259971648; // Math.PI / 360
  const DIAMETER = 12742000; // 2 * 6371000

  const phi1 = lat1 * TO_RAD;
  const phi2 = lat2 * TO_RAD;
  const dPhiHalf = (lat2 - lat1) * TO_RAD_HALF;
  const dLambdaHalf = (lon2 - lon1) * TO_RAD_HALF;

  const sinDPhiHalf = Math.sin(dPhiHalf);
  const sinDLambdaHalf = Math.sin(dLambdaHalf);

  const a = sinDPhiHalf * sinDPhiHalf +
            Math.cos(phi1) * Math.cos(phi2) *
            sinDLambdaHalf * sinDLambdaHalf;

  return DIAMETER * Math.asin(Math.sqrt(a));
}

const N = 10000000;
let sum1 = 0, sum2 = 0;

console.time('old');
for (let i = 0; i < N; i++) {
  sum1 += haversineDistanceOld(34.0522, -118.2437, 40.7128, -74.0060);
}
console.timeEnd('old');

console.time('new');
for (let i = 0; i < N; i++) {
  sum2 += haversineDistanceNew(34.0522, -118.2437, 40.7128, -74.0060);
}
console.timeEnd('new');

console.log('Sums match:', Math.abs(sum1 - sum2) < 0.001 * N);
