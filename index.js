const express = require('express');
const mongoose = require('mongoose'); // Optional: if using MongoDB
const cors = require('cors');
require('dotenv').config(); // Loads environment variables from a .env file

const app = express();
const PORT = process.env.PORT || 3000;

// ==========================================
// 1. MIDDLEWARE
// ==========================================
app.use(cors()); // Enables Cross-Origin Resource Sharing (allows frontend to talk to backend)
app.use(express.json()); // Parses incoming JSON payloads in request bodies
app.use(express.urlencoded({ extended: true })); // Parses URL-encoded data

// ==========================================
// 2. DATABASE CONNECTION (Example: MongoDB)
// ==========================================
// Uncomment this if you are using MongoDB with Mongoose
/*
mongoose.connect(process.env.MONGO_URI)
  .then(() => console.log('Database connected successfully'))
  .catch((err) => console.error('Database connection error:', err));
*/

// ==========================================
// 3. ROUTES
// ==========================================
// Basic health check route
app.get('/', (req, res) => {
  res.json({ status: 'success', message: 'Welcome to PropertyPlug API!' });
});

// Import and mount your feature routes here later, for example:
// const propertyRoutes = require('./routes/propertyRoutes');
// app.use('/api/properties', propertyRoutes);

// ==========================================
// 4. ERROR HANDLING MIDDLEWARE
// ==========================================
// Catch-all for undefined routes (404)
app.use((req, res, next) => {
  res.status(404).json({ error: 'Route not found' });
});

// Global error handler
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ error: 'Something went wrong on the server!' });
});

// ==========================================
// 5. START SERVER
// ==========================================
app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
  
});
